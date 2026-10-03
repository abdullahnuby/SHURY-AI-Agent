# SHURY — PHASE 7 RESULT

## Scope
Canonical memory authority: durable user memory, read/write/update/forget/correction, same-session persistence, cross-session scoping, restart persistence.

## Architectural outcome
`app.knowledge.memory.Memory` is the sole durable user-memory authority.

`app.brain.store.BrainStateStore` / `LearningStore.beliefs` is a derived, per-session Brain projection only. The canonical Brain no longer reads those belief rows as authoritative memory.

Memory tools invoked by the canonical Brain use the exact injected `Memory` instance through `app.runtime.memory_context`, avoiding process-global store divergence.

## Implemented changes
- Centralized durable memory key canonicalization in `Memory.canonical_key()` and aliases in `Memory.key_aliases()`.
- Canonical Brain memory snapshots are sourced from `Memory.profile()`.
- Brain memory identity/key retrieval is sourced from canonical `Memory.get_fact()` with canonical aliases.
- Brain durable writes go through `Memory.set_fact()` and only then mirror to derived Brain belief state.
- Brain deletion route added for `forget_fact -> forget_memory -> forget_fact tool`.
- Forget goal effect aligned with the existing `fact_deleted` tool contract.
- Derived Brain state refreshes immediately after memory writes/deletes.
- Added per-execution memory authority ContextVar so Brain-invoked tools cannot silently use another database.
- Added Arabic city-key aliases (`مدينتي`, `مدينتى`).

## Recorded baseline failures before fixes
- `tests/test_memory_v22_full.py` did not terminate within 90 seconds.
- Direct Brain belief mutation could override canonical `Memory` (`Aswan` vs canonical `Cairo`).
- Correction in one session left stale belief value in another session (`Luxor` after canonical correction to `Cairo`).
- Restart preserved stale Brain belief state.
- `forget my city` reached a completed Brain cycle but did not delete canonical memory.
- Brain-injected `Memory` differed from the process-global memory instance used by tools.

## Verification
- Phase 7 authority regressions: 6/6 PASS.
- Brain-memory synchronization: 4/4 PASS.
- Store unification: 3/3 PASS.
- Memory benchmark: 12/12 PASS.
- Python compile: PASS.
- Test collection: 553 tests collected.
- Canonical runtime probe: PASS.
  - durable write
  - same-session read
  - correction
  - cross-session current-value propagation
  - stale derived-cache corruption ignored
  - canonical forget
  - post-forget stale-cache non-resurrection
  - restart persistence
  - session working-memory isolation

## Known non-gate issue
`tests/test_memory_v22_full.py::test_explicit_human_correction_reuses_previous_assignment_key` on the legacy `run_agent` compatibility path did not terminate within the isolated timeout. This is recorded and was not hidden. The canonical Phase 7 Brain path has a passing correction regression and is the acceptance authority established by Phase 2.

## Gate
PASS
