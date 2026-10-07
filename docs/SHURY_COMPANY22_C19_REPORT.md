# SHURY Company 22 — C19 Implementation Report

Version: `25.8.0-alpha1-company22`
Base: `25.7.0-alpha1-company21`
Phase: **C19 — Capacity & Budget Guardrails**

## Roadmap status

The official Company Master Plan ended its pre-defined roadmap at C18. C19 was therefore introduced as a new bounded milestone rather than presented as an existing planned phase. After C19, there is currently no pre-defined C20 in the roadmap.

## Why C19

C18 made delegation load-aware and ranked cost, but capacity and cost were not enforceable preflight limits. C19 adds explicit caller-supplied guardrails while preserving organizational facts and governance boundaries.

## Files changed

- `app/organization/capacity.py`
- `app/organization/company.py`
- `tests/test_company22_c19_capacity_budget.py`
- `docs/SHURY_COMPANY_MASTER_PLAN.md`
- `docs/SHURY_COMPANY_TODO.md`
- `CHANGELOG_COMPANY22.md`
- `VERSION`

## Acceptance behavior

1. Within declared cost/capacity limits → allowed.
2. Cost overflow → rejected before execution.
3. Specialist/total active capacity overflow → rejected using canonical portfolio state.
4. Missing or invalid constrained cost evidence → fail closed.
5. Without a budget → route behavior remains unchanged.

## Exact verification results

### Company suite
`tests/test_company_*.py` split into three deterministic groups:
- Group 1: **64 passed in 20.29s**
- Group 2a: **29 passed in 13.53s**
- Group 2b: **32 passed in 11.23s**
- Total: **125/125 passed**

The initial second-group 120-second runner timed out after four completed tests; it was not treated as a test result. The remaining tests were rerun in smaller deterministic groups with the results above.

### Required gates + C19
- `test_organization_core_v1.py` + `test_layer5_canonical_runtime.py` + `test_real_skill_lifecycle.py` + C19: **19 passed in 12.02s**
- C15–C18 numbered regression + C19: **40 passed in 12.26s**

### Static/runtime gates
- `python -m compileall -q app tests`: **PASS**
- `app/data/*.db`: **APP_DATA_DB_CLEAN**

### Regression proof against C18
The C19 test module was copied into the unmodified C18 release and failed during collection with:
`ModuleNotFoundError: No module named 'app.organization.capacity'`
This demonstrates that the C19 capacity/budget contract was absent from the C18 baseline.

## Constraints preserved

- `Arabic-Retrieval-v1.0` unchanged.
- No LLM fallback.
- No new persistence store.
- No operation-name or sentence-specific routing.
- Ownership, authority, reviewer policy, and SkillBank lifecycle remain immutable under C19.

## Additional issue found

The first C19 focused test draft used a synthetic capability (`analysis`) that was not declared by the organization catalog. That was a test-fixture defect, not a product defect; it was corrected to use the real `data_analysis` / `profile_dataset` contract. No organization ownership data was changed to satisfy the test.
