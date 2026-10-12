"""Typed models for the agent's long-term memory system.

The models deliberately stay provider-independent: a memory item is useful whether
it was extracted deterministically or supplied by the retrieval-native semantic interpreter.
"""
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.knowledge.memory_schema import CANONICAL_MEMORY_FIELDS, validate_memory_record_mapping


@dataclass(frozen=True)
class MemoryRecord:
    """Canonical logical durable-memory record for Phase 3.

    The record uses ``memory_type`` and ``normalized_value`` as the canonical
    vocabulary. ``MemoryItem`` below remains the storage/retrieval compatibility
    shape and can be converted losslessly to/from this model.
    """

    id: int
    memory_type: str
    key: str | None
    value: str
    normalized_value: str
    owner_id: str | None
    scope: str
    session_id: str | None
    run_id: str | None
    source: str
    source_ref: str | None
    confidence: float
    importance: int
    created_at: str
    updated_at: str
    valid_at: str | None
    invalid_at: str | None
    expires_at: str | None
    revision: int
    status: str
    supersedes_id: int | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_memory_record_mapping(self.to_mapping(), require_id=True)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "owner_id": self.owner_id,
            "scope": self.scope,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "key": self.key,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "source": self.source,
            "source_ref": self.source_ref,
            "confidence": self.confidence,
            "importance": self.importance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expires_at": self.expires_at,
            "revision": self.revision,
            "status": self.status,
            "supersedes_id": self.supersedes_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_item(cls, item: "MemoryItem") -> "MemoryRecord":
        return cls(
            id=item.id, memory_type=item.kind, key=item.key, value=item.value,
            normalized_value=item.normalized, owner_id=item.owner_id, scope=item.scope,
            session_id=item.session_id, run_id=item.run_id, source=item.source,
            source_ref=item.source_ref, confidence=item.confidence, importance=item.importance,
            created_at=item.created_at, updated_at=item.updated_at, valid_at=item.valid_at,
            invalid_at=item.invalid_at, expires_at=item.expires_at, revision=item.revision,
            status=item.status, supersedes_id=item.supersedes_id, metadata=dict(item.metadata),
        )


@dataclass(frozen=True)
class MemoryItem:
    """Backward-compatible retrieval shape. Canonical aliases are exposed below."""

    id: int
    kind: str
    key: str | None
    value: str
    scope: str
    owner_id: str | None
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

    @property
    def memory_type(self) -> str:
        return self.kind

    @property
    def normalized_value(self) -> str:
        return self.normalized

    @property
    def normalized(self) -> str:
        # Retrieval code historically computes normalization from key/value.
        # The canonical record stores it explicitly; this compatibility property
        # is only used for in-memory legacy consumers.
        return " ".join((str(self.key or "").strip(), str(self.value or "").strip())).strip()

    def to_record(self) -> MemoryRecord:
        return MemoryRecord.from_item(self)


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
    @property
    def memory_type(self) -> str:
        """Canonical Phase-4 name; ``kind`` remains a compatibility field."""
        return self.kind

    def __post_init__(self) -> None:
        from app.knowledge.memory_types import contract_for
        contract_for(self.kind)

    metadata: dict[str, Any] = field(default_factory=dict)
