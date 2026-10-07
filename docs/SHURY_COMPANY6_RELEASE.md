# SHURY Company 6 Release

Version: `24.3.0-alpha1-company6`
Company schema: `5`

Company 6 implements Department Execution Contexts. CEO assignments are now materialized into a bounded runtime context before each canonical tool call. The context is task-scoped, least-privilege, and fail-closed for dependency access.

## Runtime contract

`CompanyAssignment -> DepartmentExecutionContext -> authorized tool -> observed result`

The context exposes only the current task's tool, capability, skill, explicit dependencies, relevant handoff ids, and owned capabilities. `{{sN}}` references require `sN` to appear in `depends_on`.

The context is ephemeral and stored in a `ContextVar`; only structural metadata is copied to `CognitiveState`. Raw outputs remain transient and can be consumed by later steps only through explicit plan dependencies/handoffs.

## Verification

- Company/organization suite: **43/43 PASS**
- Canonical context + runtime targeted suite: **17/17 PASS**
- `compileall`: **PASS**
- Existing V23 brain regression: **5/5 PASS**
- Canonical runtime smoke: **8/8 PASS**

A broader repository-wide suite can still contain legacy/environment-sensitive tests; those are not counted as Company 6 release evidence.
