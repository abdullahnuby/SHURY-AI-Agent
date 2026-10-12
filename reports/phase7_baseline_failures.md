# SHURY Phase 7 — Baseline Failures (pre-fix)

Recorded before Phase 7 fixes.

## Process-level
- `tests/test_memory_v22_full.py`: pytest process did not terminate within 90 seconds; partial output was not treated as a pass.

## Memory authority divergence
1. Durable user memory is stored in `app.knowledge.memory.Memory` (`memory_items` / legacy `facts`).
2. `app.brain.store.BrainStateStore`/`LearningStore` also stores `beliefs` per session and the Brain reads those beliefs as first-class memory evidence.
3. A direct `BrainStateStore.upsert_belief(session=A, predicate=city, value=Aswan)` made the canonical Brain answer `Aswan` while canonical `Memory.get_fact("city")` remained `Cairo`.
4. Restart preserved the stale `Aswan` Brain belief.

## Cross-session stale memory
- Session A: `Luxor` -> correction to `Cairo`.
- Session B still returned `Luxor` because its session-scoped Brain belief projection was not invalidated by the global durable memory correction.

## Forget routing
- Direct canonical Brain runtime for `forget my city` returned `I need: goal_or_capability`.
- Semantic Layer 2 identified `forget_fact`, but Brain operation normalization had no `forget_fact -> memory deletion` mapping and the Brain planner had no forget-memory method.

## Passing baseline capabilities
- Same-session write/read worked.
- Same-session correction worked.
- Durable Memory itself persisted across a new `Memory(path)` instance.
- Store unification suite: 3/3 passed.
- Brain/Memory synchronization gap suite: 4/4 passed.
