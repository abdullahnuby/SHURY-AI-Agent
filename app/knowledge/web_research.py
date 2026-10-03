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
                "latency_ms": res.latency_ms, "text": text}

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
                      "text": fetched["text"]}
            if index and fetched["text"]:
                try:
                    indexed = self.rag.index_external_text(fetched["url"], hit["title"], fetched["text"],
                                                           {"source_kind": "web", "sha256": fetched["sha256"], "query": query})
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
        """One bounded research workflow across selected Web/arXiv/GitHub providers.

        Providers are independently selectable so a higher-level policy engine can route
        research without changing the underlying network safety boundary.
        """
        providers = tuple(dict.fromkeys(str(x).casefold() for x in providers))
        web = self.research(query, limit=web_limit, index=index) if "web" in providers else {"sources": [], "count": 0}
        papers = self.arxiv_research(query, limit=paper_limit, index=index) if "arxiv" in providers else {"papers": [], "count": 0, "indexed": 0}
        repos = self.github_search(query, limit=repo_limit) if "github" in providers else {"repositories": [], "count": 0}
        repo_details = []
        # Learn from a small, relevance-ranked public-project sample.
        if "github" in providers:
            for row in repos.get("repositories", [])[:2]:
                try:
                    repo_details.append(self.github_research(row["full_name"], query=query, file_limit=8, index=index))
                except Exception as exc:
                    repo_details.append({"repo": row.get("full_name"), "error": str(exc)})
        indexed = sum(1 for x in web.get("sources", []) if x.get("indexed")) + int(papers.get("indexed", 0))
        indexed += sum(int(x.get("indexed_files", 0)) for x in repo_details)
        legacy_policy = "web + arXiv + GitHub discovery → bounded fetch → provenance → local-RAG" if set(providers) == {"web", "arxiv", "github"} else "provider policy → bounded fetch → provenance → local-RAG"
        return {"query": query, "providers": list(providers), "web": web, "arxiv": papers, "github": repos,
                "github_details": repo_details, "indexed_items": indexed,
                "policy": legacy_policy,
                "note": "external content is evidence; it is not automatically treated as truth or executable instructions"}

    def github_search(self, query: str, limit: int = 8) -> dict:
        rows=self.gateway.github_search_repositories(query, limit=limit)
        return {"query":query,"repositories":rows,"count":len(rows),"policy":"GitHub REST repository discovery; updated-first; no code mutation"}

    def arxiv_research(self, query: str, limit: int = 8, index: bool = True) -> dict:
        rows=self.gateway.arxiv_search(query, limit=limit)
        indexed=0
        for row in rows:
            abstract=row.get("abstract","")
            if not abstract or not index:
                continue
            payload=f"Title: {row.get('title','')}\nAuthors: {', '.join(row.get('authors',[]))}\nPublished: {row.get('published','')}\nURL: {row.get('url','')}\n\nAbstract: {abstract}"
            try:
                self.rag.index_external_text(row["url"], row["title"], payload,
                                             {"source_kind":"arxiv","query":query,"published":row.get("published"),"updated":row.get("updated"),"sha256":__import__('hashlib').sha256(payload.encode('utf-8')).hexdigest()})
                indexed += 1
            except Exception:
                pass
            row["indexed"] = True
        return {"query":query,"papers":rows,"count":len(rows),"indexed":indexed,
                "policy":"arXiv official API→newest-first→abstract provenance→local-RAG"}

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
                   "text": text}
            if index and text.strip():
                try:
                    row["indexed"] = self.rag.index_external_text(item["url"], path, text,
                                                                     {"source_kind": "github", "repo": repo,
                                                                      "branch": meta.get("default_branch"), "path": path,
                                                                      "sha256": item["sha256"]})
                except Exception as exc:
                    row["index_error"] = str(exc)
            files.append(row)
        return {"repo": repo, "default_branch": meta.get("default_branch"),
                "description": meta.get("description", ""), "stars": meta.get("stargazers_count"),
                "files": files, "indexed_files": sum(1 for x in files if x.get("indexed")),
                "policy": "metadata→tree→relevant files→provenance→local-RAG"}
