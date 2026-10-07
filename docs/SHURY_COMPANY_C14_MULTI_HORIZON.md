# SHURY Company C14 — Multi-Horizon Company

## Purpose

C14 adds a persistent company portfolio layer for multiple concurrent projects. Project state is not
stored in a second memory backend: active portfolio state is persisted in the canonical LearningStore,
while durable organizational knowledge remains in CompanyMemory under the existing `company` scope.

## Model

`CompanyProject` is the durable project identity and contains objective, priority, horizon, criticality,
status and metadata. `CompanyProjectTask` is a project-scoped execution item with explicit dependencies,
resource claims, assignment and status.

`SpecialistIdentity` is stable across sessions/processes because its identity key is derived from the
organization role key. Performance and reliability are reconstructed from the persisted
`company_delegation_evidence` table in the existing LearningStore.

## Isolation

Every structured GoalSpec can carry `project_id` and `horizon`. The canonical Brain binds the goal to
that project before planning. The Company execution context carries the same project id, and its context
identifier includes the project boundary. Company Memory recall can be filtered by project id; unrelated
project memories are not returned through the project-filtered retrieval lane.

## Prioritization

Cross-project prioritization is deterministic and combines project priority, criticality, horizon,
aging, active load and dependency waiting. Reprioritization changes ordering only; it does not rewrite
ownership facts or mutate specialist identity.

## Runtime synchronization

When a project-scoped coordination is created, its Company tasks are synchronized into the portfolio.
Completed and failed runtime steps update the corresponding project task status. This keeps the
portfolio aligned with actual execution without duplicating the Brain's canonical task state.

## CLI

- `/company-project-create <id|name|objective|priority|horizon>`
- `/company-projects`
- `/company-project <id>`
- `/company-priorities`
- `/company-identities`

## Gate

C14 is complete when concurrent active projects remain isolated, project-specific memory does not leak,
specialist identities survive process recreation, priorities can change deterministically, and project
task state follows real execution.
