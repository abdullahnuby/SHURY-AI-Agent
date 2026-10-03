# Phase 12 — Query-Aware Memory Retrieval

## Contract

The semantic layer emits a `MemoryQueryPlan` with:

- `need`
- `memory_types`
- `stores`
- `rationale`
- `confidence`

The Brain carries the same requirement on `SemanticFrame`. The canonical `Memory`
authority consumes that plan and selects only the required memory lanes.

## Routing classes

| Semantic need | Memory classes | Purpose |
|---|---|---|
| `user_fact` | `fact`, `preference`, `note` | identity and personal durable facts |
| `episodic` | `episode` | previous interactions, tasks, outcomes |
| `procedural_experience` | `procedural`, `episode` | verified methods plus originating experience |
| `entity_relation` | `entity`, `relation` | canonical identity and relationships |
| `knowledge` | `knowledge` | explicitly classified memory knowledge; RAG remains separate |
| `working_context` | `working`, `episode` | current/deictic task context |
| `mixed_personal` | `fact`, `preference`, `note`, `episode` | conservative generic memory search |
| `none` | none | non-memory turns |

## Security order

The memory requirement does not weaken Phase 2 or Phase 11. The effective order remains:

`semantic requirement → scope/owner filtering → temporal eligibility → hybrid ranking`

A selected memory class cannot bypass ownership, session, run, or knowledge-scope constraints.

## Canonical path

`USER → NLP → SEMANTIC FRAME → MEMORY REQUIREMENT → MEMORY CONTROLLER → SCOPED RETRIEVAL → BRAIN`

The semantic parser no longer performs an eager all-store `recall_context()` call. Memory
retrieval happens only after the semantic need has been established, or through an
explicitly supplied plan to the memory controller.
