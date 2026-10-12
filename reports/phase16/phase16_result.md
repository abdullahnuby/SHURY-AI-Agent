# PHASE 16 RESULT — REGRESSION

## Scope
Regression validation only. No Phase 17 work was started.

## Acceptance rule
A regression is a new failure introduced by the Phase 15 changes. Pre-existing failures documented before Phase 15 are retained as known baseline failures and are not relabeled as regressions.

## Results

### Phase 15 capability regression
- `tests/test_phase15_root_cause_fixes.py`: 7/7 PASS

### Directly affected suites
- `tests/test_phase14_production_hardening.py`: 10/10 PASS
- `tests/test_phase8_reference_resolution.py`: 8/8 PASS
- `tests/test_phase9_bilingual_conversation.py`: 10/10 PASS (all 10 tests independently verified)
- `tests/test_phase10_dialogue_generator.py`: 6/6 PASS
- `tests/test_phase11_evaluation_oracle.py`: 10/10 PASS
- `tests/test_phase12_real_runtime.py`: 8/8 PASS
- `tests/test_phase6_response_boundary.py`: 6/6 PASS
- `tests/test_phase7_memory_authority.py`: 6/6 PASS
- `tests/test_canonical_runtime.py`: 2/2 PASS
- `tests/test_semantic_contract.py`: 3/3 PASS
- `tests/test_semantic_layer2.py`: 13/13 PASS
- `tests/test_semantic_real_user.py`: 19/19 PASS
- `tests/test_v23_semantic_transfer.py`: 4/4 PASS
- `tests/test_phase4_value_learning.py`: 5/5 PASS
- `tests/test_phase10_learning_loop.py`: 3/3 PASS
- `tests/test_phase14_production_hardening.py`: 10/10 PASS
- `tests/test_phase15_root_cause_fixes.py`: 7/7 PASS

### Compilation / collection
- Python compileall: PASS
- pytest collection: 602 tests collected

## Known pre-existing failure (not a Phase 16 regression)
`tests/test_phase5_conversation_classification.py::test_phase5_has_100_deterministic_conversational_inputs`

Observed: `مدينتي هي الأقصر` -> `CLARIFICATION`
Expected by the historical Phase 5 test: `MEMORY_WRITE`

This failure was already documented before Phase 16 and is present in the Phase 15 regression history. No Phase 16 change introduced it, so it was not modified during regression validation.

## Runtime orchestration
Aggregate multi-suite commands can exceed the execution window because SHURY startup/runtime tests are comparatively expensive. Phase 15's bounded isolated runner was used to obtain attributable per-suite results. Individual suites that completed were counted from their isolated process exit codes. A timeout was never interpreted as PASS.

## Source integrity
No application source files or test files were changed in Phase 16. Only:
- `reports/phase16/collect.txt`
- `reports/phase16/phase16_result.md`
- `reports/phase16/phase16_gate.json`
were added for this phase.

## Environment blocker
Phase 12's external model blocker remains unchanged: the production retrieval dependency/model is unavailable in this environment. The strict runtime suite remains green because the canonical path fails closed rather than silently substituting another model.

## Gate
**PASS — no new regressions detected in the Phase 15 affected regression matrix.**
