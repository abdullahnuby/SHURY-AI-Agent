# SHURY Company C10 — Company Memory

Company memory is a namespace inside the single canonical `Memory` store. It is not a second database and is never inherited from user/session/run memory.

## Categories

- `decision` — structured CEO/team decisions.
- `ownership` — verified responsibility facts.
- `procedure` — reusable procedures with execution evidence.
- `lesson` — verified lessons from failures.
- `review_finding` — independent QA/security findings.
- `outcome` — structured execution outcomes.

## Boundary

Company memory uses the explicit `company` scope and a stable company owner id. User memory remains in user/session/run scopes. Retrieval is explicit through `CompanyMemory`; the normal user memory controller does not implicitly merge these records.

## Acceptance

A later company task can retrieve verified organizational knowledge relevant to its goal without inheriting the previous task context, outputs, or user memory.
