"""Strict Phase-4 memory-type contract.

The contract separates *what kind of memory a record is* from its ownership
scope. It is deliberately deterministic and provider-independent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet

GLOBAL_SYSTEM = "global_system"
KNOWLEDGE = "knowledge"
USER = "user"
SESSION = "session"
RUN = "run"
MEMORY_SCOPES = frozenset({GLOBAL_SYSTEM, KNOWLEDGE, USER, SESSION, RUN})
LEGACY_SCOPE_ALIASES = {"global": GLOBAL_SYSTEM}

WORKING = "working"
SESSION_MEMORY = "session"
FACT = "fact"
PREFERENCE = "preference"
EPISODE = "episode"
ENTITY = "entity"
RELATION = "relation"
PROCEDURE = "procedural"
KNOWLEDGE_MEMORY = "knowledge"
NOTE = "note"
SYSTEM = "system"
RUN_MEMORY = "run"

CANONICAL_MEMORY_TYPES = frozenset({
    WORKING,
    SESSION_MEMORY,
    FACT,
    PREFERENCE,
    EPISODE,
    ENTITY,
    RELATION,
    PROCEDURE,
    KNOWLEDGE_MEMORY,
    NOTE,
    SYSTEM,
    RUN_MEMORY,
})


@dataclass(frozen=True)
class MemoryTypeContract:
    """Behavioral contract for one logical memory type."""

    memory_type: str
    purpose: str
    storage: str
    allowed_scopes: FrozenSet[str]
    owner_required: bool
    session_required: bool
    run_required: bool
    lifetime: str
    write_policy: str
    read_policy: str
    forget_policy: str
    temporal_policy: str
    retrieval_priority: int
    durable: bool = True


# Priority is metadata for the future retrieval controller. Phase 4 does not
# change the scoring function yet; it only makes the intended priority explicit.
MEMORY_TYPE_CONTRACTS: dict[str, MemoryTypeContract] = {
    WORKING: MemoryTypeContract(
        WORKING, "Current-turn temporary context", "memory_working", frozenset({SESSION}),
        True, True, False, "short-lived / expires with context", "record_working_context only",
        "same owner + exact session", "working_clear or expiry", "expires_at only", 100, durable=False,
    ),
    SESSION_MEMORY: MemoryTypeContract(
        SESSION_MEMORY, "Conversation/task-scoped durable context", "memory_items", frozenset({SESSION}),
        True, True, False, "current conversation/task", "remember with scope=session",
        "same owner + exact session", "scoped forget / session cleanup", "valid_at/invalid_at/expires_at", 90,
    ),
    FACT: MemoryTypeContract(
        FACT, "Explicit user fact, identity or correction", "memory_items", frozenset({USER}),
        True, False, False, "long-term", "explicit/validated fact write", "same user", "selective forget; history retained",
        "validity intervals + supersession", 85,
    ),
    PREFERENCE: MemoryTypeContract(
        PREFERENCE, "Explicit user preference", "memory_items", frozenset({USER}),
        True, False, False, "long-term until changed", "explicit/validated preference write", "same user",
        "selective forget; history retained", "validity intervals + supersession", 80,
    ),
    EPISODE: MemoryTypeContract(
        EPISODE, "Prior interaction/task experience", "memory_episodes", frozenset({USER, SESSION, RUN}),
        True, False, False, "durable experience history", "record_episode only", "same owner; session/run filtering",
        "selective owner-scoped deletion; history is append-oriented", "timestamp/session/run chronology", 70,
    ),
    ENTITY: MemoryTypeContract(
        ENTITY, "Canonical entity identity and aliases", "memory_entities", frozenset({USER, KNOWLEDGE, GLOBAL_SYSTEM, SESSION, RUN}),
        False, False, False, "durable until corrected/removed", "link_entity only", "scope/owner constrained",
        "selective removal/update", "created/updated timestamps", 65,
    ),
    RELATION: MemoryTypeContract(
        RELATION, "Typed relationship between entities", "memory_relations", frozenset({USER, KNOWLEDGE, GLOBAL_SYSTEM, SESSION, RUN}),
        False, False, False, "durable until invalidated", "link_relation only", "subject scope + owner constrained",
        "selective invalidation/removal; source history retained", "valid_at/invalid_at", 64,
    ),
    PROCEDURE: MemoryTypeContract(
        PROCEDURE, "Verified reusable method from successful experience", "memory_items", frozenset({USER}),
        True, False, False, "long-term; evidence-dependent", "promote only from verified repeated success",
        "same user", "selective forget; evidence remains in episodes", "supersession + recency", 60,
    ),
    KNOWLEDGE_MEMORY: MemoryTypeContract(
        KNOWLEDGE_MEMORY, "Imported/project/world knowledge with provenance", "memory_items", frozenset({KNOWLEDGE}),
        False, False, False, "durable until source invalidation", "imported/system knowledge only",
        "explicit knowledge scope only", "source-aware removal", "validity/expiry/source lifecycle", 55,
    ),
    NOTE: MemoryTypeContract(
        NOTE, "Legacy/general user note kept distinct from facts", "memory_items", frozenset({USER}),
        True, False, False, "long-term until forgotten", "add_note / compatibility note write only",
        "same user", "selective forget", "validity/expiry", 45,
    ),
    SYSTEM: MemoryTypeContract(
        SYSTEM, "Explicit globally visible system classification", "memory_items", frozenset({GLOBAL_SYSTEM}),
        False, False, False, "system lifetime", "system-owned writes only", "globally visible system lane",
        "system-controlled only", "system validity/expiry", 40,
    ),
    RUN_MEMORY: MemoryTypeContract(
        RUN_MEMORY, "Execution-run scoped transient/durable evidence", "memory_items", frozenset({RUN}),
        True, True, True, "run lifetime", "explicit run-scoped write", "same owner + exact session + run",
        "run cleanup / selective forget", "validity + run boundary", 75,
    ),
}


def normalize_memory_type(value: str | None) -> str:
    raw = str(value or "").strip().casefold()
    aliases = {
        "working_memory": WORKING,
        "working-context": WORKING,
        "session_memory": SESSION_MEMORY,
        "preference_memory": PREFERENCE,
        "procedural": PROCEDURE,
        "procedure": PROCEDURE,
        "procedural_memory": PROCEDURE,
        "knowledge_memory": KNOWLEDGE_MEMORY,
        "run_memory": RUN_MEMORY,
    }
    return aliases.get(raw, raw)


def contract_for(memory_type: str) -> MemoryTypeContract:
    canonical = normalize_memory_type(memory_type)
    try:
        return MEMORY_TYPE_CONTRACTS[canonical]
    except KeyError as exc:
        raise ValueError(
            f"unsupported memory type: {memory_type!r}; expected one of {sorted(CANONICAL_MEMORY_TYPES)}"
        ) from exc


def validate_memory_type_operation(
    memory_type: str,
    *,
    scope: str,
    owner_id: str | None,
    session_id: str | None,
    run_id: str | None,
    operation: str,
    source: str | None = None,
    key: str | None = None,
) -> MemoryTypeContract:
    """Validate the type/scope contract before a memory operation is persisted."""
    contract = contract_for(memory_type)
    # Structural memory types are owned by their dedicated APIs. Rejecting them
    # before scope validation keeps the error deterministic and prevents them
    # from being represented as generic durable memory items.
    if contract.memory_type in {WORKING, EPISODE, ENTITY, RELATION} and operation == "remember":
        raise ValueError(f"memory type {contract.memory_type!r} has a dedicated storage API; do not persist it via remember()")
    canonical_scope = LEGACY_SCOPE_ALIASES.get(str(scope).strip().casefold(), str(scope).strip().casefold())
    if canonical_scope not in MEMORY_SCOPES:
        raise ValueError(f"unsupported memory scope: {scope!r}")
    if canonical_scope not in contract.allowed_scopes:
        raise ValueError(
            f"memory type {contract.memory_type!r} cannot use scope {canonical_scope!r}; "
            f"allowed scopes: {sorted(contract.allowed_scopes)}"
        )
    if contract.owner_required and not owner_id:
        raise ValueError(f"memory type {contract.memory_type!r} requires owner_id")
    if not contract.owner_required and canonical_scope in {GLOBAL_SYSTEM, KNOWLEDGE} and owner_id is not None:
        raise ValueError(f"memory type {contract.memory_type!r} is not user-owned")
    if contract.session_required and not session_id:
        raise ValueError(f"memory type {contract.memory_type!r} requires session_id")
    if contract.run_required and not run_id:
        raise ValueError(f"memory type {contract.memory_type!r} requires run_id")
    # USER-scoped long-term/graph records may retain session/run provenance without
    # changing their logical type or scope. SESSION/RUN types remain exact-scope lanes.
    provenance_allowed = {FACT, PREFERENCE, NOTE, PROCEDURE, ENTITY, RELATION}
    if canonical_scope not in {SESSION, RUN} and session_id is not None and contract.memory_type not in provenance_allowed:
        raise ValueError(f"session_id is not valid for memory type {contract.memory_type!r} in scope {canonical_scope!r}")
    if canonical_scope != RUN and run_id is not None and contract.memory_type not in {FACT, PREFERENCE, NOTE, PROCEDURE, EPISODE, ENTITY, RELATION}:
        raise ValueError(f"run_id is not valid for memory type {contract.memory_type!r} outside its run scope")
    if contract.memory_type in {KNOWLEDGE_MEMORY, SYSTEM} and source == "user":
        raise ValueError(f"memory type {contract.memory_type!r} cannot be written with user provenance")
    if contract.memory_type in {FACT, PREFERENCE} and not key:
        raise ValueError(f"memory type {contract.memory_type!r} requires a canonical key")
    if contract.memory_type == KNOWLEDGE_MEMORY and not str(key or "").strip():
        raise ValueError("knowledge memory requires a stable key for provenance-aware management")
    if contract.memory_type == SYSTEM and not str(key or "").strip():
        raise ValueError("system memory requires a stable key")
    return contract
