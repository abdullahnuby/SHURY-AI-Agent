# SHURY Phase 11 — Baseline / Failure Record

Phase 11 scope: deterministic evaluation oracle only.

## Baseline evidence

- Phase 10 corpus: 1,000 sessions / 3,216 turns.
- All eight required per-turn expectation fields are present in 3,216 / 3,216 turns.
- `expected_final_state` is present in 1,000 / 1,000 sessions.
- Existing `app/evaluation/judge.py` checks only `status` and optional `required_tools` and cannot compare the Phase 11 structured contract.

## Failures recorded before correction

1. Oracle implementation defect: entity normalization was called through `cls` inside an instance method (`NameError`).
2. Oracle launcher defect: `scripts/validate_oracle.py` failed to import `app` when run as a script because the repository root was not on `sys.path`.
3. First real-runtime comparison showed representation mismatches that the oracle must report: localized Arabic values vs canonical English expectation values, parser intent `recall_fact` vs canonical Brain operation `query_identity`, and unresolved-reference target representation.

No source runtime fix was made in response to these semantic mismatches during this phase.
