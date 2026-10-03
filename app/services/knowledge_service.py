"""RAG orchestration facade (V16 adaptive portfolio by default)."""
from app.knowledge.rag import RAGEngine
from app.knowledge.rag_v16 import AdaptiveRAGEngine
from app.knowledge.knowledge_base import KnowledgeBase


def index_knowledge(path: str, *, project_id: str | None = None, provenance: dict | None = None, source_ref: str | None = None):
    return KnowledgeBase().add(path, project_id=project_id, provenance=provenance, source_ref=source_ref)


def add_knowledge_text(source_ref: str, title: str, text: str, *, project_id: str | None = None, provenance: dict | None = None):
    return KnowledgeBase().add_text(source_ref, title, text, project_id=project_id, provenance=provenance)


def remove_knowledge(source_ref: str, *, project_id: str | None = None) -> bool:
    return KnowledgeBase().remove(source_ref, project_id=project_id)


def list_knowledge(*, project_id: str | None = None, limit: int = 100) -> list[dict]:
    return KnowledgeBase().list(project_id=project_id, limit=limit)


def index_agent_memory():
    return RAGEngine().index_memory()


def ask_knowledge(query: str, top_k: int = 6, *, project_id: str | None = None):
    return AdaptiveRAGEngine().query(query, top_k=top_k, project_id=project_id)


def rag_runtime_stats():
    engine = RAGEngine()
    return {"index": engine.stats(), "decay": engine.decay_report(), "engine": "v16_adaptive_portfolio"}


def agentic_rag_query(query: str, max_rounds: int = 3, max_evidence: int = 24):
    from app.services.agentic_rag_service import agentic_rag
    return agentic_rag(query, max_rounds=max_rounds, max_evidence=max_evidence)
