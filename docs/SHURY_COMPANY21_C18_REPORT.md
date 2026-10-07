# SHURY Company 21 — C18 Release Report

Version: `25.7.0-alpha1-company21`
Base: `25.6.0-alpha1-company20`
Phase: **C18 — Adaptive Delegation & Load-Aware Routing**

## Why C18
C17 completed conservative evidence calibration for specialist selection. The next bounded Company milestone was load-aware adaptive delegation: use canonical runtime evidence plus current canonical portfolio load to rank already-qualified candidates without changing ownership or authority.

## Scope implemented
- Added `app/organization/routing.py` with `AdaptiveDelegationController`, `RoutingCandidate`, and `RoutingEvidence`.
- Integrated the controller as a secondary signal in `app/organization/team.py`.
- Reused the same secondary routing order in `app/organization/recovery.py` after existing eligibility/evidence checks.
- Added `SHURYCompany.route_candidates()` in `app/organization/company.py`.
- Added `/company-routing <capability>` in `app/interfaces/cli.py`.
- Extended `tests/test_company21_c18_adaptive_routing.py` to cover canonical store requirements, load-aware ranking, ownership filtering, role filtering, and CLI inspection.
- Added stale-runtime DB cleanup to `tests/conftest.py` so source-tree DB artifacts cannot contaminate the runtime-artifact gate.
- Updated `VERSION`, master plan, TODO, changelog, and C18 design documentation.

## Acceptance behavior
1. Ownership/qualification is checked first; routing cannot make an unqualified candidate eligible.
2. Only builder roles in the proven owning department survive routing.
3. Capability fit remains dominant; verified evidence, current active workload, risk, and cost are secondary signals.
4. Current workload is read from canonical `LearningStore` project/task state.
5. Recovery still escalates on authorization/approval/context/dependency failures.
6. No routing operation mutates ownership, role authority, reviewer policy, or SkillBank lifecycle.
7. The CLI surface is read-only inspection; it does not grant execution authority.

## Regression proof against C17
Running the new C18 test file against the C17 release failed during collection with:

`ModuleNotFoundError: No module named 'app.organization.routing'`

This proves the C18 routing surface was absent from the C17 baseline.

## Additional issue found and fixed
A full C18 gate exposed that `app/data/skills.db` could remain from a previous non-isolated invocation and contaminate the existing runtime-artifact assertion. The pytest autouse runtime isolation fixture now removes stale `*.db` artifacts before each test and cleans them after each test. The artifact gate was rerun successfully.

## Exact test results
### Company suite (all `tests/test_company_*.py`)
Split into two deterministic groups because the single long runner exceeded the execution wall-clock budget:
- Group 1: `64 passed in 21.02s`
- Group 2: `61 passed in 15.54s`
- Total: **125/125 passed**

### Required external gates
- `tests/test_organization_core_v1.py`: included in combined gate
- `tests/test_layer5_canonical_runtime.py`: included in combined gate
- `tests/test_real_skill_lifecycle.py`: included in combined gate

Combined required/compatibility group:
`47 passed in 15.30s`

This combined run also covered:
- C16 learning loop
- C15 CLI governance closure
- C17 competency calibration
- C18 routing
- C18 hardening and runtime-artifact checks

### Focused C18/adjacent regression before final gate
`23 passed in 11.02s`

### Source/packaging gates
- `python -m compileall -q app tests`: `SOURCE_COMPILE_PASS`
- runtime DB artifact gate: `APP_DATA_DB_CLEAN`
- release ZIP integrity: `ZIP_TEST_PASS`

## Boundaries preserved
- `Arabic-Retrieval-v1.0` unchanged.
- No LLM fallback introduced.
- No new learning/competency database introduced.
- No sentence-specific or operation-name-specific routing introduced.
- C19 not started.
