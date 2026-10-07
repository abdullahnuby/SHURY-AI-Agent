# Company 6 — Department Execution Contexts

## Added

- `DepartmentExecutionContext` for task-scoped organizational execution.
- ContextVar lifecycle around every canonical tool invocation.
- Explicit dependency-reference authorization for `{{sN}}` plan bindings.
- Least-privilege current-tool authorization.
- Explicit inbound/outbound Company handoff identifiers in context.
- Structural context metadata in `CognitiveState`.
- Regression coverage for cross-department isolation and context cleanup.

## Security/Integrity

- Undeclared dependency references are rejected before the tool executes.
- Raw task outputs are not persisted into organizational context.
- Durable user memory remains under the existing memory subsystem and is not silently re-scoped to departments.
- Memory result ownership (`remember_result` / `fact_saved`) is explicitly assigned to the Memory department.

## Verification

- Company suite: 51/51 PASS
- Context isolation suite: 39/39 PASS before final metadata-only hardening
- Canonical targeted runtime suite: 17/17 PASS
- `compileall`: PASS
