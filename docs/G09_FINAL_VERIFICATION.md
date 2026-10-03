# SHURY G09.x Final Verification — 2026-10-01

## Canonical architecture
- `LearningStore` is the single persistence owner for learning state, transition evidence/history, beliefs, and cognitive events.
- `app/brain/store.py` contains no database schema; `BrainStateStore` is a compatibility facade over `LearningStore`.
- `app/brain/learning.py` aliases `BrainExperienceStore` to `LearningStore`.
- `app/learning/brain_store.py` is a compatibility facade over `LearningStore`; legacy `brain.db` is migration source only.
- Legacy `brain_state.db` import is explicit for custom stores and automatic only for the default production database.

## LLM boundary
- Canonical Brain planning/execution is LLM-independent.
- `run_cognitive` routes language perception into a validated structured goal, then invokes canonical Brain execution.
- `run_react` is disabled by default.
- `run_legacy_llm_react` is an explicit compatibility/benchmark surface.
- Legacy LLM tests are marked `legacy_llm` and are not part of canonical cognitive authority.

## Gap closure
- G01 Model invalidation/drift: verified.
- G02 Meta-strategy controller: verified.
- G03 Structured procedural memory + generalization: verified; value-slot transfer acceptance added.
- G04 Failure + recovery learning: verified.
- G05 Evaluation proofs/metrics: verified.
- G06 Causal learning: verified.
- G07 Architecture boundary closure: verified.
- G08 Integration/proof hardening: verified.
- G09.x Integration/release boundary: verified.

## Test gates
- Phase 2–9 regression: 54 passed.
- Phase 10–14 + gap/learning regression: 47 passed.
- Gap-focused + V23/evaluation/real-user regression: 75 passed.
- Store/boundary regression: 35 passed.
- Procedure family transfer proof: 3 passed.
- Release-contained canonical gate (Phase 2–14 + G01–G09 + V23 core): **143 passed**.
- Release smoke: compile/import/schema initialization passed.

## Release hygiene
- Generated SQLite databases are excluded from the release archive.
- Logs, `.pyc`, and `__pycache__` are excluded.
- Archive integrity verified with `unzip -tq`.
- SHA-256 recorded alongside the release archive.
