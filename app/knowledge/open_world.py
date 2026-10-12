"""Open-world research and learning loop.

The engine turns the existing bounded Web/arXiv/GitHub gateway into a reusable learning
loop: route by intent, acquire heterogeneous evidence, score novelty/quality, persist
provenance, index useful content into RAG, and compile only declarative Skill candidates.
No external prose becomes executable instructions.
"""
from __future__ import annotations

from pathlib import Path
import math
import re
from urllib.parse import urlparse

from app.knowledge.web_research import WebResearchEngine, _tokens
from app.knowledge.research_memory import ResearchMemory
from app.skills.research import research_to_candidate
from app.integrations.devops import inspect_project, git_status


def _freshness(value: str | None) -> float:
    if not value:
        return 0.2
    text = str(value)[:10]
    m = re.match(r"(20\d\d)-(\d\d)-(\d\d)", text)
    if not m:
        return 0.2
    try:
        import datetime as dt
        d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        age = max(0, (dt.date.today() - d).days)
        return math.exp(-age / 240.0)
    except Exception:
        return 0.2


def _domain_quality(url: str) -> float:
    host = (urlparse(url).hostname or "").casefold()
    if host.endswith(".gov") or host.endswith(".edu") or host.endswith(".ac.uk"):
        return 1.0
    if host in {"github.com", "raw.githubusercontent.com"}:
        return 0.92
    if host.endswith(".org"):
        return 0.86
    if host.endswith(".com"):
        return 0.74
    return 0.68


def _route(query: str, memory: ResearchMemory | None = None) -> list[tuple[str, str]]:
    g = query.casefold()
    routes: list[tuple[str, str]] = []
    research = any(x in g for x in ("research", "paper", "papers", "latest", "newest", "أحدث", "بحث", "ابحاث", "أبحاث"))
    code = any(x in g for x in ("github", "code", "implementation", "repo", "repository", "تنفيذ", "كود", "مستودع"))
    data = any(x in g for x in ("data", "dataset", "analysis", "algorithm", "statistics", "بيانات", "تحليل", "خوارزمية", "إحصاء"))
    if research or not routes:
        routes.append(("arxiv", "scientific literature"))
    if code or research or data:
        routes.append(("github", "implementation evidence"))
    routes.append(("web", "current documentation and broader evidence"))
    out=[]
    seen=set()
    for x in routes:
        if x[0] not in seen:
            out.append(x); seen.add(x[0])
    if memory is None or len(out) < 2:
        return out
    # Historical source utility orders providers, but never removes a provider that the
    # current query explicitly needs. Unobserved providers get a small exploration bonus.
    stats={r["source_kind"]:r for r in memory.source_stats(query)}
    total=sum(int(v.get("observations",0)) for v in stats.values())
    scored=[]
    for idx,(kind,reason) in enumerate(out):
        row=stats.get(kind)
        if not row:
            u=0.62 + 0.10/(idx+1)
        else:
            n=max(1,int(row.get("observations",0)))
            mean_reward=float(row.get("mean_reward",0.0))
            u=mean_reward + 0.18*((math.log(total+1)/n)**0.5)
        scored.append((u,kind,reason))
    scored.sort(key=lambda x:(-x[0],x[1]))
    return [(k,r) for _,k,r in scored]


class OpenWorldResearchEngine:
    def __init__(self, research: WebResearchEngine | None = None, memory: ResearchMemory | None = None):
        self.research = research or WebResearchEngine()
        self.memory = memory or ResearchMemory()

    def _normalize_evidence(self, result: dict, query: str) -> list[dict]:
        out: list[dict] = []
        terms = set(_tokens(query))
        for x in result.get("web", {}).get("sources", []):
            text = f"{x.get('title','')} {x.get('snippet','')} {x.get('text','')[:5000]}"
            overlap = len(terms & set(_tokens(text))) / max(1, len(terms))
            out.append({"source_kind":"web","title":x.get("title",""),"url":x.get("url",""),
                        "sha256":x.get("sha256",""),"relevance":overlap,"quality":_domain_quality(x.get("url","")),
                        "freshness":_freshness(x.get("published")),"indexed":bool(x.get("indexed")),
                        "metadata":{"snippet":x.get("snippet",""),"query":query}})
        for x in result.get("arxiv", {}).get("papers", []):
            text = f"{x.get('title','')} {x.get('abstract','')}"
            overlap = len(terms & set(_tokens(text))) / max(1, len(terms))
            out.append({"source_kind":"arxiv","title":x.get("title",""),"url":x.get("url",""),
                        "sha256":"","relevance":overlap,"quality":1.0,"freshness":_freshness(x.get("published")),
                        "indexed":bool(x.get("indexed")),"metadata":{"authors":x.get("authors",[]),"published":x.get("published",""),"query":query}})
        for x in result.get("github", {}).get("repositories", []):
            text = f"{x.get('full_name','')} {x.get('description','')}"
            overlap = len(terms & set(_tokens(text))) / max(1, len(terms))
            out.append({"source_kind":"github","title":x.get("full_name", ""),"url":x.get("html_url", ""),
                        "sha256":"","relevance":overlap,"quality":0.92,"freshness":_freshness(x.get("updated_at")),
                        "indexed":False,"metadata":{"stars":x.get("stargazers_count",0),"language":x.get("language"),"query":query}})
        # De-duplicate URLs while retaining the best evidence score.
        best={}
        for e in out:
            key=e.get("url") or (e.get("source_kind"), e.get("title"))
            score=0.55*e["relevance"]+0.25*e["quality"]+0.20*e["freshness"]
            if key not in best or score > best[key][0]:
                best[key]=(score,e)
        rows=[e for _,e in best.values()]
        rows.sort(key=lambda e:(-(0.55*e["relevance"]+0.25*e["quality"]+0.20*e["freshness"]),e["source_kind"],e["title"]))
        return rows

    def learn(self, query: str, *, web_limit: int = 6, paper_limit: int = 8, repo_limit: int = 6, index: bool = True) -> dict:
        query=query.strip()
        if not query:
            raise ValueError("query is required")
        route=_route(query, self.memory)
        providers=tuple(x[0] for x in route)
        # Existing WebResearchEngine bounds every individual provider. V20 adds a second
        # policy layer that orders providers from observed utility while still exploring
        # all sources required by the current query.
        result=self.research.internet_research(query, web_limit=web_limit, paper_limit=paper_limit, repo_limit=repo_limit, index=index, providers=providers)
        evidence=self._normalize_evidence(result, query)
        prior=self.memory.related(query, limit=40)
        prior_urls={x.get("url") for x in prior if x.get("url")}
        for e in evidence:
            e["novelty"] = 0.0 if e.get("url") in prior_urls else 1.0
        # Persist source-class utility as an operational signal.
        for kind in {e["source_kind"] for e in evidence}:
            group=[e for e in evidence if e["source_kind"]==kind]
            reward=sum(0.55*e["relevance"]+0.25*e["quality"]+0.20*e["freshness"] for e in group)/max(1,len(group))
            novelty=sum(e["novelty"] for e in group)/max(1,len(group))
            self.memory.observe_source(query,kind,reward+0.15*novelty,len(group),verified=False)
        run_id=self.memory.record_run(query,{"routes":route,"policy":"current evidence + learned source utility + novelty","index":index},evidence,indexed_count=sum(1 for e in evidence if e.get("indexed")))
        candidate=research_to_candidate(query,[
            {"url":e.get("url"),"title":e.get("title"),"sha256":e.get("sha256"),"source":e.get("source_kind"),"score":e.get("relevance")}
            for e in evidence[:10]
        ])
        return {"run_id":run_id,"query":query,"route":[{"source":a,"reason":b} for a,b in route],
                "evidence":evidence[:24],"evidence_count":len(evidence),
                "new_evidence_count":sum(1 for e in evidence if e.get("novelty",0)>0),
                "candidate_skill":candidate.get("candidate"),"source_learning":self.memory.source_stats(query),
                "prior_related":prior[:8],"policy":"research→score→dedupe→persist→RAG index→declarative Skill candidate",
                "safety":"external content remains evidence; no web prose becomes executable workflow"}

    def development_learning(self, path: str) -> dict:
        project=Path(path).expanduser().resolve()
        inspection=inspect_project(str(project))
        git=git_status(str(project))
        stack=" ".join(inspection.get("stack",[]))
        query=f"software development build test manage {stack}".strip()
        research=self.learn(query, web_limit=4, paper_limit=4, repo_limit=5, index=True)
        return {"path":str(project),"inspection":inspection,"git":git,"research_query":query,
                "research_run_id":research["run_id"],"evidence_count":research["evidence_count"],
                "candidate_skill":research["candidate_skill"],
                "policy":"inspect→observe git→research stack→store evidence→candidate skill; no source code mutation"}
