"""Typed models for the agent's long-term memory system.

The models deliberately stay provider-independent: a memory item is useful whether
it was extracted deterministically or supplied by the retrieval-native semantic interpreter.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryItem:
    id: int
    kind: str
    key: str | None
    value: str
    scope: str
    session_id: str | None
    run_id: str | None
    source: str
    source_ref: str | None
    confidence: float
    importance: int
    sensitivity: str
    status: str
    created_at: str
    updated_at: str
    valid_at: str | None = None
    invalid_at: str | None = None
    expires_at: str | None = None
    last_accessed: str | None = None
    access_count: int = 0
    revision: int = 1
    supersedes_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryHit:
    item: MemoryItem
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryCandidate:
    kind: str
    value: str
    key: str | None = None
    confidence: float = 0.8
    importance: int = 3
    source: str = "auto"
    sensitivity: str = "normal"
    valid_at: str | None = None
    invalid_at: str | None = None
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
