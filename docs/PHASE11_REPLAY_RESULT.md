# SHURY Phase 11 — Replay Result

## Implemented

1. Durable `ReplayItem` metadata now stores `model_version` and `model_change_recency`.
2. Replay priority keeps the existing transparent signals and adds bounded pressure for experiences captured under recently changed world-model versions.
3. Exact state/action contexts recompute novelty and contradiction after new evidence arrives, avoiding a permanently-novel first sample.
4. `LearningStore` migrates existing `replay_items` tables in place when the new columns are absent.
5. Replay audit rows record state/action value deltas while empirical visit counts remain unchanged by replay.
6. The runtime transition builder persists the world-model version used for the prediction before the live model is updated.
7. A replay inspection mode is available through `recent_model` / `model_recent` / `recent_model_change`.

## Safety boundary

Replay only consumes persisted experience and updates learned value estimates. It does not call runtime tools, execute side effects, grant authority, or bypass verification/policy.

## Verification

- `python -m compileall -q app` — passed.
- Phase 2 replay regression + Phase 11 replay tests — 15 passed.
- Phases 3–11 targeted regression set — 56 passed.
- V23 architecture/cognitive loop + learning/chat/runtime/import regression set — 54 passed.

The full repository suite was started, but the pre-existing suite exceeded the five-minute execution gate before completion; no failure was reported in the portion executed.
