"""V17 internet, research and development orchestration facade."""
from __future__ import annotations
from app.integrations.network import NetworkGateway, extract_text
from app.knowledge.web_research import WebResearchEngine
from app.integrations.devops import inspect_project, git_status, check_project


def network_status():
    return NetworkGateway().stats()


def fetch_web(url: str):
    res = NetworkGateway().fetch(url)
    return {"url": res.final_url, "status": res.status, "content_type": res.content_type,
            "sha256": res.sha256, "bytes": len(res.body), "text": extract_text(res.body, res.content_type, res.final_url)[:80_000],
            "latency_ms": res.latency_ms, "cached": res.cached}


def research_web(query: str):
    return WebResearchEngine().research(query, limit=5, index=True)

def internet_research(query: str):
    return WebResearchEngine().internet_research(query, web_limit=5, paper_limit=6, repo_limit=5, index=True)


def research_github(repo: str):
    return WebResearchEngine().github_research(repo, file_limit=24, index=True)

def research_arxiv(query: str):
    return WebResearchEngine().arxiv_research(query, limit=8, index=True)

def search_github(query: str):
    return WebResearchEngine().github_search(query, limit=8)


def inspect_repo(path: str):
    return inspect_project(path)


def git_repo_status(path: str):
    return git_status(path)


def validate_project(path: str, checks=("git-diff-check", "compile")):
    return check_project(path, checks)
