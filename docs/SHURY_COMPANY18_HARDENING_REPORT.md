# SHURY Company 18 — C15 Hardening Report

Version: `25.4.0-alpha2-company18`
Base: `25.4.0-alpha1-company17`

## Scope

C15 hardening only. C16 was not started. No LLM fallback was added and `Arabic-Retrieval-v1.0` was not replaced.

## Fixes and evidence

| # | Fix | Changed files | New/updated test | Result |
|---|---|---|---|---|
| 1 | Acquisition trust is always quarantined; independent reviewer must grant `local`/`trusted` with reason; governed trust event is required by apply | `app/organization/self_improvement.py`, `app/learning/store.py` | `test_acquisition_cannot_self_grant_trust`, `test_trust_grant_requires_independent_reviewer_reason_and_event`, `test_apply_requires_governed_trust_even_if_skill_field_was_tampered` | PASS |
| 2 | Mandatory registered producer; producer stored in proposal; producer cannot review/approve; rejection events recorded | `app/organization/self_improvement.py` | `test_missing_producer_is_fail_closed_and_self_review_is_logged`, `test_approve_rejects_when_ceo_is_also_producer` | PASS |
| 3 | Rollback requires CEO/security reviewer + reason; canonical proposal ledger record with before/after and `skill_rollback/applied` | `app/organization/self_improvement.py` | `test_rollback_requires_authority_and_creates_applied_change_record` | PASS |
| 4 | Apply stores pre-mutation Company/Skill baseline, enters `monitoring`; monitor returns `keep`/`recommend_rollback` and never rolls back | `app/organization/self_improvement.py` | `test_apply_enters_monitoring_and_monitor_never_rolls_back` | PASS |
| 5 | Acquisition regression executes executable verification cases in isolation; no cases/failure blocks; records Company before/after + change-specific result | `app/organization/self_improvement.py` | `test_acquisition_regression_gate_rejects_without_verification_cases_directly`, `test_regression_records_change_specific_and_company_before_after` | PASS |
| 6 | Apply rechecks approval fingerprint; QA review is assignment/tool driven rather than operation-name driven; DB paths isolated under pytest tmp | `app/organization/self_improvement.py`, `app/organization/review.py`, `tests/conftest.py` | `test_apply_fingerprint_rejects_tampered_promotion_payload_directly`, `test_review_rejects_new_operation_without_required_security_assignment`, `test_company_suite_does_not_write_db_files_into_app_data` | PASS |

Additional updated regression coverage is in `tests/test_company18_hardening.py`; runtime artifact coverage is in `tests/test_company18_runtime_artifacts.py`.

## Exact test runs

### Requested Company suite

`pytest -q tests/test_company_architecture.py ... tests/test_company_team_formation.py`

**125 passed in 29.15s**

This is the complete 125-test `tests/test_company_*.py` set, run explicitly in a stable order. A wildcard-only invocation was also attempted; one batch invocation timed out, while the explicit complete set finished green.

### Requested organization core

`pytest -q tests/test_organization_core_v1.py`

**8 passed in 9.44s**

### Requested Layer-5 canonical runtime

`pytest -q tests/test_layer5_canonical_runtime.py`

**1 passed in 9.49s**

### Requested real Skill lifecycle

`pytest -q tests/test_real_skill_lifecycle.py`

**4 passed in 8.57s**

### C18 hardening + artifact guard

`pytest -q tests/test_company18_hardening.py tests/test_company18_runtime_artifacts.py`

**14 passed + 1 passed = 15 passed** (the combined final run with the requested extra suites reported **28 passed in 15.18s**).

### Final combined extra gates

`pytest -q tests/test_organization_core_v1.py tests/test_layer5_canonical_runtime.py tests/test_real_skill_lifecycle.py tests/test_company18_hardening.py tests/test_company18_runtime_artifacts.py`

**28 passed in 15.18s**

`python -m compileall -q app tests`

**COMPILEALL_PASS**

Post-run artifact assertion:

**APP_DATA_DB_CLEAN** — no `*.db` files under `app/data`.

## Old C15 baseline proof

The same C18 hardening tests were run selectively against the original Company 17/C15 ZIP. The old code failed the new contracts, including:

- acquisition producer contract (`unexpected keyword argument 'producer'`)
- missing mandatory producer (`KeyError` instead of fail-closed producer validation)
- rollback authority (`unexpected keyword argument 'actor'`)
- monitoring (`_isolated_company_eval`/monitoring lifecycle absent)
- change-specific acquisition regression (`_isolated_company_eval` absent; old gate had no verification-case execution)
- fingerprint enforcement (old `apply` did not raise after payload mutation)
- generic/new-operation QA security contract (old generic review returned `ok=True` for an operation lacking the required security reviewer)

This establishes that the added tests exercise behavior absent from C15 rather than only restating existing behavior.

## Additional issue found during this pass

One existing integration test depended on the old operation-specific QA final-message wording. The new generic reviewer initially returned a generic message, causing that test to fail. This was corrected by deriving the message from the actual assignment/department and move result; no operation-name branch was reintroduced.

No unrelated issue was fixed outside the requested hardening scope.
