# SHURY — Phase 5 Memory Ingestion

## Canonical pipeline

```text
RAW EPISODE
    ↓
CANDIDATE MEMORY
    ↓
VALIDATION
    ↓
DEDUPLICATION / CONFLICT CHECK
    ↓
PROMOTION
    ↓
LONG-TERM MEMORY
```

## Rules enforced

- Every observed user turn is first recorded as an episodic record.
- Ordinary conversation does not become long-term memory automatically.
- Only explicit high-confidence `FACT` / `PREFERENCE` candidates are eligible for automatic promotion.
- Fact and preference promotion requires a stable key and confidence >= 0.90.
- Secret-bearing turns remain episodic, but secret values are redacted before persistence.
- Identical active memories are deduplicated instead of creating another durable record.
- A same-key conflicting value is explicitly marked as a conflict and is promoted through the canonical `Memory` authority, where revision/supersession preserves history.
- Candidate provenance is carried by `source_ref=episode:<episode_id>` on promoted memory.
- Structural memory types are not auto-promoted through generic candidate storage.
- `Memory` remains the sole persistence authority; `MemoryIngestionController` only decides ingestion/promotion.

## Evidence

Focused Phase 5 and prior-memory regression: 76/76 passing.
Broader memory/semantic/kernel regression: 135/135 passing.
Memory benchmark: passing.
Python compilation: passing.

## Deliberate non-changes

Phase 5 does not redesign retrieval, temporal conflict policy, entity resolution, Brain planning, learning, or migration. Those remain separate phases in the memory architecture plan.
