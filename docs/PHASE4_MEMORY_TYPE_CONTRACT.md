# SHURY — Phase 4 Memory-Type Contract

## Status

DONE — strict memory-type contract implemented and targeted/regression tested.

## Purpose

Phase 4 makes `memory_type` an explicit behavioral contract. Scope/ownership and memory type are separate dimensions. A type may only use its declared storage and lifecycle rules.

## Canonical types

Required target types:

- `working` — current-turn temporary context; `memory_working`; session-owned; dedicated `record_working_context()` API.
- `session` — conversation/task context; `memory_items`; exact `session` scope.
- `fact` — explicit user fact, identity, or correction; user scope; canonical key; historical supersession.
- `preference` — explicit user preference; user scope; canonical key; historical supersession.
- `episode` — prior interaction/task experience; `memory_episodes`; dedicated `record_episode()` API.
- `entity` — canonical entity/aliases; `memory_entities`; dedicated `link_entity()` API.
- `relation` — typed entity relation; `memory_relations`; dedicated `link_relation()` API.
- `procedural` (canonical; `procedure` is accepted as an alias) — verified reusable method derived from repeated successful experience; user scope.
- `knowledge` — imported/world/project knowledge with explicit provenance; `knowledge` scope.

Compatibility/operational extensions are intentionally explicit rather than implicit:

- `note` — legacy general user note, kept separate from facts.
- `system` — globally visible system classification in `global_system` scope.
- `run` — execution-run scoped memory item in `run` scope.

## Enforcement

`Memory.remember()` validates:

1. supported memory type
2. allowed scope
3. owner/session/run requirements
4. provenance constraints
5. key requirements for keyed types
6. dedicated storage restrictions for structural types

Structural types cannot be smuggled through generic `remember()`:

```text
working  -> record_working_context
episode  -> record_episode
entity   -> link_entity
relation -> link_relation
```

USER-scoped durable memory may retain `session_id`/`run_id` as provenance without changing its logical type or scope.

## Retrieval priority metadata

Each contract defines an explicit deterministic `retrieval_priority`. Phase 4 records the priority contract; it does not change the existing retrieval scoring/fusion algorithm. Retrieval redesign remains a later phase.

## Historical compatibility

Physical SQLite columns remain compatible with previous releases (`kind` remains storage-compatible with canonical `memory_type`). Existing legacy records are not silently retyped during this phase.

Unknown or unsupported new types are rejected at the canonical model boundary.
