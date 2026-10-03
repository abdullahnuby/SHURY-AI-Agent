"""V20 open-world research + learning facade."""
from app.knowledge.open_world import OpenWorldResearchEngine
from app.knowledge.research_memory import ResearchMemory


def learn(query: str):
    return OpenWorldResearchEngine().learn(query)


def learn_development(path: str):
    return OpenWorldResearchEngine().development_learning(path)


def research_status():
    return ResearchMemory().stats()


def research_sources(query: str = "", limit: int = 20):
    return ResearchMemory().recent_evidence(query, limit=limit)


def research_source_learning(query: str):
    mem=ResearchMemory()
    return {"query":query,"context_key":mem.context_key(query),"sources":mem.source_stats(query)}
