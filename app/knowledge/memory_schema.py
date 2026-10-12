"""Canonical durable-memory schema contract.

Phase 3 defines the logical memory record independently of SQLite's historical
column names. Existing storage columns such as ``kind`` and ``normalized`` are
kept as compatibility storage names; the canonical contract exposes them as
``memory_type`` and ``normalized_value``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

CANONICAL_MEMORY_SCHEMA_NAME = "personal-agent.memory"
CANONICAL_MEMORY_SCHEMA_VERSION = 3

CANONICAL_MEMORY_FIELDS = (
    "id",
    "memory_type",
    "owner_id",
    "scope",
    "session_id",
    "run_id",
    "key",
    "value",
    "normalized_value",
    "source",
    "source_ref",
    "confidence",
    "importance",
    "created_at",
    "updated_at",
    "valid_at",
    "invalid_at",
    "expires_at",
    "revision",
    "status",
    "supersedes_id",
    "metadata",
)

# Physical SQLite columns retained for backward compatibility with the existing
# code and databases. The right-hand side is the canonical field name.
STORAGE_TO_CANONICAL = {
    "id": "id",
    "kind": "memory_type",
    "key": "key",
    "value": "value",
    "normalized": "normalized_value",
    "scope": "scope",
    "owner_id": "owner_id",
    "session_id": "session_id",
    "run_id": "run_id",
    "source": "source",
    "source_ref": "source_ref",
    "confidence": "confidence",
    "importance": "importance",
    "sensitivity": "sensitivity",
    "status": "status",
    "created_at": "created_at",
    "updated_at": "updated_at",
    "valid_at": "valid_at",
    "invalid_at": "invalid_at",
    "expires_at": "expires_at",
    "revision": "revision",
    "supersedes_id": "supersedes_id",
    "metadata": "metadata",
}

CANONICAL_TO_STORAGE = {canonical: storage for storage, canonical in STORAGE_TO_CANONICAL.items()}


def validate_memory_record_mapping(record: Mapping[str, Any], *, require_id: bool = False) -> None:
    """Validate the Phase 3 record shape without imposing Phase 4 memory-type policy."""
    required = set(CANONICAL_MEMORY_FIELDS)
    if not require_id:
        required.discard("id")

    missing = sorted(field for field in required if field not in record)
    if missing:
        raise ValueError(f"memory record missing canonical fields: {missing}")

    if require_id and not isinstance(record.get("id"), int):
        raise TypeError("memory record id must be an integer")
    if not isinstance(record.get("value"), str) or not record["value"].strip():
        raise ValueError("memory record value must be a non-empty string")
    if not isinstance(record.get("memory_type"), str) or not record["memory_type"].strip():
        raise ValueError("memory record memory_type must be a non-empty string")
    from app.knowledge.memory_types import contract_for
    contract_for(record["memory_type"])
    if not isinstance(record.get("scope"), str) or not record["scope"].strip():
        raise ValueError("memory record scope must be a non-empty string")
    if not isinstance(record.get("status"), str) or not record["status"].strip():
        raise ValueError("memory record status must be a non-empty string")

    confidence = float(record.get("confidence", 1.0))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("memory record confidence must be between 0 and 1")

    importance = int(record.get("importance", 3))
    if not 1 <= importance <= 5:
        raise ValueError("memory record importance must be between 1 and 5")

    revision = int(record.get("revision", 1))
    if revision < 1:
        raise ValueError("memory record revision must be >= 1")

    for field in ("created_at", "updated_at", "valid_at", "invalid_at", "expires_at"):
        value = record.get(field)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"memory record {field} must be an ISO-like timestamp or null")
            _parse_timestamp(field, value)

    created = record.get("created_at")
    updated = record.get("updated_at")
    if created and updated and _parse_timestamp("created_at", created) > _parse_timestamp("updated_at", updated):
        raise ValueError("memory record created_at cannot be after updated_at")

    valid_at = record.get("valid_at")
    invalid_at = record.get("invalid_at")
    if valid_at and invalid_at and _parse_timestamp("valid_at", valid_at) >= _parse_timestamp("invalid_at", invalid_at):
        raise ValueError("memory record valid_at must be before invalid_at")


def _parse_timestamp(field: str, value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"memory record {field} is not a valid ISO timestamp: {value!r}") from exc
