# SHURY Company 20 — C17 Implementation Report

Version: `25.6.0-alpha1-company20`
Base: `25.5.0-alpha1-company19`

## A. C16 pending issue — closed before C17

The C16 report recorded a bounded C15 CLI integration issue: legacy Company self-improvement commands did not satisfy the mandatory `producer` / `actor` / `reason` arguments added by C15 Hardening.

Changed:
- `app/interfaces/cli.py`
- `tests/test_company20_c15_cli_governance.py`

Closed behavior:
- `/company-improve-skill <skill-key>|<producer>` passes `producer`.
- `/company-acquire-skill <key>|<name>|<source>|<producer>|<json-workflow>` passes `producer`.
- `/company-skill-trust <proposal_id>|<reviewer>|<local|trusted>|<reason>` exposes the separate governed trust step.
- `/company-skill-rollback <skill-key>|<actor>|<reason>` passes rollback authority and reason.
- The CLI banner documents the governed forms.

Test:
`tests/test_company20_c15_cli_governance.py` — **4 passed in 11.06s**.

Old-code proof: the same test file was designed around the C15-gov API contract and fails against the unpatched C16 CLI because those calls are made without the new mandatory arguments.

No unrelated C15/C16 issue was changed here.

## B. C17 — Evidence-Calibrated Workforce

### C17.1 — Conservative competency calibration

Files:
- `app/organization/competency.py`
- `app/organization/__init__.py`
- `tests/test_company20_c17_competency.py`

Implementation:
- Reads only canonical `LearningStore.company_delegation_evidence`.
- Computes observed and conservative success rates.
- Uses a 95% Wilson lower confidence bound.
- Labels evidence as `insufficient_evidence`, `proven`, `mixed`, or `weak`.

Tests:
- one verified success remains insufficient and conservative
- repeated verified success reaches `proven`
- missing canonical LearningStore fails closed

### C17.2 — Team selection integration

Files:
- `app/organization/team.py`
- `app/organization/registry.py`
- `app/organization/company.py`
- `tests/test_company20_c17_competency.py`
- `tests/test_company_team_formation.py`

The existing `history_score` remains the secondary signal. C17 blends calibrated organization evidence only when that evidence exists for the same capability/specialist/tool. Ownership and team-size minimization are unchanged.

Test:
`test_c17_team_history_score_blends_canonical_competency_evidence_after_skill_history`.

Existing team-formation tests remained green as part of the combined C17/local validation run (**14 passed in 9.07s total across the three test files**).

### C17.3 — CLI visibility

Files:
- `app/interfaces/cli.py`
- `tests/test_company20_c17_competency.py`

Added `/company-competency [capability]|[specialist]`.

Test:
`test_c17_cli_reports_calibrated_profiles`.

## C. Old-code regression proof

C17 tests require `CompanyCompetencyCalibrator`, which does not exist in the C16 base. Running the C17 test contract against the old base therefore fails at import; the patched tree passes the same contract.

The C15 CLI hardening test requires the governed C15 API arguments, which are absent from the old C16 CLI call sites.

## D. Verification status

Local C17-focused validation:

```text
pytest -q tests/test_company20_c17_competency.py tests/test_company20_c15_cli_governance.py tests/test_company_team_formation.py
14 passed in 9.07s
```

## E. Exact final verification

```text
pytest -q tests/test_company_*.py
125 passed in 26.08s

pytest -q tests/test_organization_core_v1.py
8 passed in 10.28s

pytest -q tests/test_layer5_canonical_runtime.py
1 passed in 9.96s

pytest -q tests/test_real_skill_lifecycle.py
4 passed in 7.83s

pytest -q tests/test_company18_hardening.py tests/test_company18_runtime_artifacts.py tests/test_company19_c16_learning_loop.py tests/test_company20_c15_cli_governance.py tests/test_company20_c17_competency.py tests/test_company_team_formation.py
34 passed in 15.48s

source compilation (app + tests)
SOURCE_COMPILE_PASS

app/data runtime artifact check
APP_DATA_DB_CLEAN
```

A single process running the entire gate sequence timed out after the Company wildcard completed. This was treated as a runner-level timeout, not as a test result. Every remaining required suite was rerun independently and produced the exact results above.

## F. Constraints

- No LLM fallback added.
- `omarelshehy/Arabic-Retrieval-v1.0` unchanged.
- No new persistence store.
- No sentence-specific hardcoded routing rule.
- No operation-name hardcoding introduced.
- C17 does not mutate ownership/authority or execute lifecycle/governance changes automatically.
