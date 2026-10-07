"""Research orchestration over the V17 network gateway + local RAG.

The engine is deterministic: search results are fetched, normalized, scored by lexical
coverage/freshness/domain signals, persisted with provenance, and optionally indexed into
local RAG. No model, embedding service, or remote summarizer is required.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone
from collections import Counter
from urllib.parse import urlparse
from app.integrations.network import NetworkGateway, extract_text
from app.knowledge.rag import RAGEngine


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w\u0600-\u06ff]+", text.lower(), flags=re.UNICODE)


def _domain_score(url: str) -> float:
    host = urlparse(url).hostname or ""
    if host.endswith(".gov") or host.endswith(".edu") or host.endswith(".ac.uk"):
        return 1.0
    if host == "github.com" or host.endswith(".githubusercontent.com"):
        return 0.92
    if host.endswith(".org"):
        return 0.85
    return 0.70


_RESEARCH_STOPWORDS = {
    "search", "find", "look", "compare", "choose", "select", "best", "latest", "recent",
    "papers", "paper", "research", "studies", "study", "report", "save", "create", "make",
    "report", "about", "regarding", "within", "last", "years", "year", "internet", "web",
    "أحدث", "آخر", "سنتين", "ابحث", "بحث", "قارن", "اختر", "أفضل", "تقرير", "احفظ",
    "أنشئ", "إنشاء", "على", "عن", "خلال", "سنة", "سنتين", "الإنترنت", "الانترنت",
    "الويب", "أبحاث", "أوراق", "دراسات", "موثوقة", "موثوق", "للـ", "لل", "ثم", "من",
}


def _research_topic(query: str) -> str:
    """Extract the substantive research topic from an action-heavy user request.

    This is capability-level normalization: task verbs and artifact instructions are
    removed before querying providers, so provider search is about the subject rather
    than the surrounding workflow language.
    """
    text = re.sub(r"\s+", " ", str(query or "")).strip()
    # Prefer the text after common topic introducers and before the next action clause.
    patterns = (
        r"(?:about|on|regarding)\s+(.+?)(?=\s+(?:and then|then|compare|save|create|choose)\b|$)",
        r"(?:عن|حول|بخصوص)\s+(.+?)(?=\s+(?:وقارن|ثم|واحفظ|أنشئ|اختر)\b|$)",
    )
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            text = m.group(1).strip(" .،,:;")
            break
    tokens = [t for t in _tokens(text) if t not in _RESEARCH_STOPWORDS and len(t) > 2]
    # Preserve a compact, deterministic topic rather than passing the entire user goal.
    return " ".join(tokens[:10]) if tokens else text[:240]


def _paper_relevance(topic: str, title: str, abstract: str) -> float:
    tt = set(_tokens(topic))
    if not tt:
        return 0.0
    title_tokens = set(_tokens(title))
    abstract_tokens = set(_tokens(abstract))
    title_cov = len(tt & title_tokens) / max(1, len(tt))
    abstract_cov = len(tt & abstract_tokens) / max(1, len(tt))
    phrase_bonus = 0.0
    topic_l = topic.casefold()
    title_l = title.casefold()
    for phrase in ("long term memory", "long-term memory", "ai agents", "agent memory", "memory agents"):
        if phrase in topic_l and phrase in title_l:
            phrase_bonus = max(phrase_bonus, 0.25)
    return min(1.0, 0.62 * title_cov + 0.28 * abstract_cov + phrase_bonus)


def _arxiv_search_query(topic: str) -> str:
    tokens = [t for t in _tokens(topic) if t not in _RESEARCH_STOPWORDS and len(t) > 2]
    if not tokens:
        return topic.strip()
    # Require the strongest topic terms while leaving the provider free to match
    # ordering and inflection. Keep the query short to avoid task-language pollution.
    important = tokens[:7]
    return " AND ".join(f'all:"{t}"' for t in important)


class WebResearchEngine:
    def __init__(self, gateway: NetworkGateway | None = None, rag: RAGEngine | None = None):
        self.gateway = gateway or NetworkGateway()
        self.rag = rag or RAGEngine()

    def search(self, query: str, limit: int = 5) -> list[dict]:
        return self.gateway.search_web(query, limit=limit)

    def fetch(self, url: str) -> dict:
        res = self.gateway.fetch(url)
        text = extract_text(res.body, res.content_type, res.final_url)
        return {"url": res.final_url, "requested_url": res.requested_url, "status": res.status,
                "content_type": res.content_type, "sha256": res.sha256, "bytes": len(res.body),
                "latency_ms": res.latency_ms, "text": text,
                "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")}

    def research(self, query: str, limit: int = 5, index: bool = True) -> dict:
        hits = self.search(query, limit=max(1, min(10, limit)))
        qt = set(_tokens(query))
        sources = []
        for hit in hits:
            try:
                fetched = self.fetch(hit["url"])
            except Exception as exc:
                sources.append({"rank": hit["rank"], "url": hit["url"], "title": hit["title"], "error": str(exc)})
                continue
            text_tokens = set(_tokens(fetched["text"]))
            lexical = len(qt & text_tokens) / max(1, len(qt))
            title_bonus = len(qt & set(_tokens(hit["title"]))) / max(1, len(qt))
            length_bonus = min(1.0, len(fetched["text"]) / 12_000.0)
            source_score = _domain_score(fetched["url"])
            score = 0.52 * lexical + 0.16 * title_bonus + 0.12 * length_bonus + 0.20 * source_score
            record = {"rank": hit["rank"], "title": hit["title"], "url": fetched["url"],
                      "snippet": hit.get("snippet", ""), "sha256": fetched["sha256"],
                      "score": round(score, 6), "lexical_coverage": round(lexical, 6),
                      "source_quality": round(source_score, 6), "bytes": fetched["bytes"],
                      "retrieved_at": fetched.get("retrieved_at"), "text": fetched["text"]}
            if index and fetched["text"]:
                try:
                    indexed = self.rag.index_knowledge_text(fetched["url"], hit["title"], fetched["text"],
                                                           provenance={"origin": "web_research", "source_kind": "web", "sha256": fetched["sha256"], "query": query})
                    record["indexed"] = indexed
                except Exception as exc:
                    record["index_error"] = str(exc)
            sources.append(record)
        sources.sort(key=lambda x: (-float(x.get("score", 0)), x.get("url", "")))
        consensus = self._consensus(sources)
        return {"query": query, "sources": sources[:limit], "count": len(sources),
                "consensus": consensus, "policy": "search→fetch→score→index→local-RAG",
                "note": "scores rank evidence candidates; they are not truth probabilities"}

    @staticmethod
    def _consensus(sources: list[dict]) -> dict:
        usable = [s for s in sources if s.get("text")]
        if len(usable) < 2:
            return {"source_count": len(usable), "agreement": 0.0, "method": "pairwise-lexical-jaccard"}
        sims = []
        for i in range(len(usable)):
            a = set(_tokens(usable[i]["text"]))
            for j in range(i + 1, len(usable)):
                b = set(_tokens(usable[j]["text"]))
                sims.append(len(a & b) / max(1, len(a | b)))
        return {"source_count": len(usable), "agreement": round(sum(sims) / max(1, len(sims)), 6),
                "method": "pairwise-lexical-jaccard"}

    def internet_research(self, query: str, web_limit: int = 5, paper_limit: int = 6, repo_limit: int = 5,
                          index: bool = True, providers=("web", "arxiv", "github")) -> dict:
        """Run bounded research with provider isolation and graceful degradation.

        Paper-focused research prefers the official arXiv API instead of scraping a search
        engine. A robots denial or temporary web-provider failure must not abort otherwise
        valid research from official APIs.
        """
        requested = tuple(dict.fromkeys(str(x).casefold() for x in providers))
        topic = _research_topic(query)
        paper_focused = bool(re.search(
            r"(?:latest|recent|newest|last\s+two\s+years|paper|papers|research|literature|arxiv|أحدث|حديث|آخر\s+سنتين|أبحاث|أوراق|دراسات|بحوث)",
            query or "", re.I))
        selected = ("arxiv",) if paper_focused else requested

        web = {"sources": [], "count": 0}
        papers = {"papers": [], "count": 0, "indexed": 0}
        repos = {"repositories": [], "count": 0}
        errors = []

        if "web" in selected:
            try:
                web = self.research(query, limit=web_limit, index=index)
            except Exception as exc:
                errors.append({"provider": "web", "error": str(exc)})
                web = {"sources": [], "count": 0, "error": str(exc)}

        if "arxiv" in selected:
            try:
                papers = self.arxiv_research(topic, limit=max(paper_limit, 12), index=index)
            except Exception as exc:
                errors.append({"provider": "arxiv", "error": str(exc)})
                papers = {"papers": [], "count": 0, "indexed": 0, "error": str(exc)}

        if "github" in selected and not paper_focused:
            try:
                repos = self.github_search(query, limit=repo_limit)
            except Exception as exc:
                errors.append({"provider": "github", "error": str(exc)})
                repos = {"repositories": [], "count": 0, "error": str(exc)}

        repo_details = []
        if "github" in selected and not paper_focused:
            for row in repos.get("repositories", [])[:2]:
                try:
                    repo_details.append(self.github_research(row["full_name"], query=query, file_limit=8, index=index))
                except Exception as exc:
                    repo_details.append({"repo": row.get("full_name"), "error": str(exc)})

        indexed = sum(1 for x in web.get("sources", []) if x.get("indexed")) + int(papers.get("indexed", 0))
        indexed += sum(int(x.get("indexed_files", 0)) for x in repo_details)
        policy = "provider policy → bounded fetch/API → provenance → local-RAG"
        if paper_focused:
            policy = "paper-focused policy → topic normalization → official arXiv API → relevance gate → provenance → local-RAG"
        return {"query": query, "topic": topic, "providers": list(selected), "requested_providers": list(requested),
                "web": web, "arxiv": papers, "github": repos, "github_details": repo_details,
                "indexed_items": indexed, "provider_errors": errors, "policy": policy,
                "note": "external content is evidence; it is not automatically treated as truth or executable instructions"}

    def github_search(self, query: str, limit: int = 8) -> dict:
        rows=self.gateway.github_search_repositories(query, limit=limit)
        return {"query":query,"repositories":rows,"count":len(rows),"policy":"GitHub REST repository discovery; updated-first; no code mutation"}

    def arxiv_research(self, query: str, limit: int = 8, index: bool = True) -> dict:
        topic = _research_topic(query)
        provider_query = _arxiv_search_query(topic)
        raw_rows = self.gateway.arxiv_search(provider_query, limit=max(limit, 12))
        scored = []
        for row in raw_rows:
            relevance = _paper_relevance(topic, row.get("title", ""), row.get("abstract", ""))
            item = dict(row)
            item["relevance"] = round(relevance, 6)
            scored.append(item)
        scored.sort(key=lambda row: (-float(row.get("relevance", 0.0)), str(row.get("published", ""))), reverse=False)
        # Do not allow arbitrary latest papers to masquerade as answers. Require a
        # minimum topic match and retain a small pool for transparent evidence.
        qualifying = [row for row in scored if float(row.get("relevance", 0.0)) >= 0.18]
        qualifying = qualifying[:max(1, min(20, limit))]
        retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        qualifying = [dict(row, retrieved_at=row.get("retrieved_at") or retrieved_at) for row in qualifying]
        indexed = 0
        for row in qualifying:
            abstract=row.get("abstract","")
            if not abstract or not index:
                continue
            payload=f"Title: {row.get('title','')}\nAuthors: {', '.join(row.get('authors',[]))}\nPublished: {row.get('published','')}\nURL: {row.get('url','')}\n\nAbstract: {abstract}"
            try:
                self.rag.index_knowledge_text(row["url"], row["title"], payload,
                                             provenance={"origin":"arxiv_research","source_kind":"arxiv","query":topic,"provider_query":provider_query,"published":row.get("published"),"updated":row.get("updated"),"sha256":__import__('hashlib').sha256(payload.encode('utf-8')).hexdigest()})
                indexed += 1
            except Exception:
                pass
            row["indexed"] = True
        return {"query": query, "topic": topic, "provider_query": provider_query, "papers": qualifying,
                "candidate_count": len(raw_rows), "count": len(qualifying), "indexed": indexed,
                "relevance_gate": {"threshold": 0.18, "qualifying": len(qualifying)},
                "policy":"topic normalization→arXiv official API→relevance gate→newest qualified evidence→abstract provenance→local-RAG"}

    def github_research(self, repo: str, query: str = "", file_limit: int = 30, index: bool = True) -> dict:
        meta = self.gateway.github_repo(repo)
        tree = self.gateway.github_tree(repo, meta.get("default_branch"), limit=200)
        interesting = []
        terms = set(_tokens(query))
        for item in tree:
            path = item.get("path", "")
            lower = path.lower()
            if any(x in lower for x in ("readme", "architecture", "docs/", "pyproject", "package.json", "requirements", "cargo.toml", "go.mod", ".github/workflows/", "makefile", "dockerfile")):
                priority = 1.0
            elif lower.endswith((".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java", ".md", ".yml", ".yaml")):
                priority = 0.55
            else:
                continue
            name_bonus = (len(terms & set(_tokens(path))) / max(1, len(terms))) if terms else 0.0
            interesting.append((priority + 0.35 * name_bonus, path, item))
        interesting.sort(key=lambda x: (-x[0], x[1]))
        files = []
        for _, path, _ in interesting[:max(1, min(file_limit, 80))]:
            try:
                item = self.gateway.github_file(repo, path, meta.get("default_branch"))
            except Exception as exc:
                files.append({"path": path, "error": str(exc)})
                continue
            text = item["text"]
            if len(text) > 120_000:
                text = text[:120_000]
            row = {"path": path, "url": item["url"], "sha256": item["sha256"], "bytes": len(item["text"]),
                   "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                   "text": text}
            if index and text.strip():
                try:
                    row["indexed"] = self.rag.index_knowledge_text(item["url"], path, text,
                                                                     provenance={"origin": "github_research", "source_kind": "github", "repo": repo,
                                                                      "branch": meta.get("default_branch"), "path": path,
                                                                      "sha256": item["sha256"]})
                except Exception as exc:
                    row["index_error"] = str(exc)
            files.append(row)
        return {"repo": repo, "default_branch": meta.get("default_branch"),
                "description": meta.get("description", ""), "stars": meta.get("stargazers_count"),
                "files": files, "indexed_files": sum(1 for x in files if x.get("indexed")),
                "policy": "metadata→tree→relevant files→provenance→local-RAG"}
