# SHURY Company C14 Release

Version: 25.3.0-alpha1-company16

## Implemented

- Multi-project portfolio persisted in the canonical LearningStore.
- Project-scoped tasks, dependencies and execution status.
- Stable specialist identities derived from organization roles and persisted delegation evidence.
- Deterministic cross-project reprioritization.
- Project-isolated execution contexts.
- Project-filtered Company Memory retrieval.
- Structured GoalSpec support for `project_id` and `horizon`.
- Canonical Brain synchronization of project tasks and runtime status.
- CLI inspection and project-management commands.

## Verification

- C14 multi-horizon tests: 7/7 PASS
- Company suite: 115/115 PASS including C14 additions
- Canonical Brain/V23 tests: 8/8 PASS
- compileall: PASS
- Release artifact scan: zero runtime-generated cache/database/log artifacts.

## Non-claims

The legacy full repository suite is not treated as green by this release. Existing failures outside
Company are tracked separately and are not hidden by the C14 gate.
