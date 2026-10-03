"""Canonical world/project knowledge boundary for Phase 9.

Knowledge is intentionally separate from personal/episodic memory. This facade manages
only knowledge sources backed by the local RAG index and requires provenance metadata.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.knowledge.rag import RAGEngine


class KnowledgeBase:
    """Source-managed knowledge store over the local RAG engine."""

    def __init__(self, rag: RAGEngine | None = None):
        self.rag = rag or RAGEngine()

    def add(self, path: str | Path, *, project_id: str | None = None,
            provenance: dict[str, Any] | None = None, source_ref: str | None = None) -> dict:
        return self.rag.index_knowledge(
            path,
            project_id=project_id,
            provenance=provenance,
            source_ref=source_ref,
        )

    def add_text(self, source_ref: str, title: str, text: str, *, project_id: str | None = None,
                 provenance: dict[str, Any] | None = None) -> dict:
        return self.rag.index_knowledge_text(
            source_ref,
            title,
            text,
            project_id=project_id,
            provenance=provenance,
        )

    def remove(self, source_ref: str, *, project_id: str | None = None) -> bool:
        return self.rag.remove_knowledge(source_ref, project_id=project_id)

    def list(self, *, project_id: str | None = None, limit: int = 100) -> list[dict]:
        return self.rag.list_knowledge(project_id=project_id, limit=limit)

    def get(self, source_ref: str, *, project_id: str | None = None) -> dict | None:
        for row in self.list(project_id=project_id, limit=10000):
            if row.get("source_ref") == source_ref or row.get("path") == source_ref:
                return row
        return None

    def stats(self, *, project_id: str | None = None) -> dict:
        return self.rag.knowledge_stats(project_id=project_id)


_DEFAULT: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = KnowledgeBase()
    return _DEFAULT
