# SHURY Company 19 — C16 Implementation Report

Version: `25.5.0-alpha1-company19`
Base: `25.4.0-alpha2-company18`

## C16.1 — Verified post-change outcomes

Files: `app/organization/self_improvement.py`, `tests/test_company19_c16_learning_loop.py`.

Implemented `record_post_change_outcome(...)` using canonical `LearningStore`, `SkillBank`, and `CompanyMemory`; it validates monitoring state, registry ownership, registered tool/capability consistency, and unseen task signatures. Verified outcomes enter canonical Company Memory and specialist reliability evidence.

Test: `test_c16_verified_outcome_feeds_memory_and_specialist_reliability`.

## C16.2 — Unseen-task generalization

Files: `app/organization/self_improvement.py`, `tests/test_company19_c16_learning_loop.py`.

Regression stores verification-case signatures. Runtime outcomes matching those signatures are rejected as non-unseen. Monitoring measures verified post-change unseen success rate independently from the single-change and general Company metrics.

Test: `test_c16_rejects_verification_task_as_unseen_outcome` and `test_c16_keep_requires_generalization_and_reports_org_level_separately`.

## C16.3 — Regression detection and rollback proposal

Files: `app/organization/self_improvement.py`, `tests/test_company19_c16_learning_loop.py`.

Monitoring now evaluates company, single-change, generalization, and organization-level gates. On failure it opens one canonical `skill_rollback` proposal, records the source proposal, and leaves the live Skill untouched.

Tests: `test_c16_regression_opens_rollback_proposal_without_auto_apply`, `test_c16_does_not_auto_open_duplicate_rollback_proposals`.

## C16.4 — Organization-level learning

Files: `app/organization/self_improvement.py`, `tests/test_company19_c16_learning_loop.py`.

Apply baseline now includes capability-scoped and organization-wide delegation reliability. Monitoring reports these separately and requires organization-level non-regression for retention.

Test: `test_c16_keep_requires_generalization_and_reports_org_level_separately`.

## CLI

File: `app/interfaces/cli.py`.

Added the C16 monitoring command without changing the underlying governance model.

## Verification

The complete C16 suite and all required pre-C16 company gates are run before release. Exact results are recorded below after execution.

## Additional issue found

C16 work exposed an existing C18 runtime-surface issue: legacy CLI commands for Company self-improvement still call the now-governed C15 methods without the mandatory `producer` / `actor` / `reason` arguments. This was **not fixed in C16** because it is a C15 CLI integration issue outside the four C16 learning-loop requirements; it is recorded here for the next bounded maintenance patch.

## Exact verification results

```text
pytest -q tests/test_company_*.py
125 passed in 27.77s

pytest -q tests/test_organization_core_v1.py
8 passed in 9.73s

pytest -q tests/test_layer5_canonical_runtime.py
1 passed in 8.83s

pytest -q tests/test_real_skill_lifecycle.py
4 passed in 8.54s

pytest -q tests/test_company18_hardening.py tests/test_company18_runtime_artifacts.py
15 passed in 10.79s

pytest -q tests/test_company19_c16_learning_loop.py
5 passed in 12.62s

python -m compileall -q app tests
PASS

app/data runtime DB check
APP_DATA_DB_CLEAN
```

A combined command containing these suites once hit the runner timeout before all later commands completed. The suites were then rerun separately and the exact results above were obtained; no timeout is counted as a test result.
