"""RAG orchestration facade (V16 adaptive portfolio by default)."""
from app.knowledge.rag import RAGEngine
from app.knowledge.rag_v16 import AdaptiveRAGEngine


def index_knowledge(path: str):
    return RAGEngine().index(path)


def index_agent_memory():
    return RAGEngine().index_memory()


def ask_knowledge(query: str, top_k: int = 6):
    return AdaptiveRAGEngine().query(query, top_k=top_k)


def rag_runtime_stats():
    engine = RAGEngine()
    return {"index": engine.stats(), "decay": engine.decay_report(), "engine": "v16_adaptive_portfolio"}


def agentic_rag_query(query: str, max_rounds: int = 3, max_evidence: int = 24):
    from app.services.agentic_rag_service import agentic_rag
    return agentic_rag(query, max_rounds=max_rounds, max_evidence=max_evidence)
