from app.knowledge.agentic_rag.orchestrator import AgenticRAGEngine


def agentic_rag(query: str, max_rounds: int = 3, max_evidence: int = 24):
    return AgenticRAGEngine().query(query, max_rounds=max_rounds, max_evidence=max_evidence)
