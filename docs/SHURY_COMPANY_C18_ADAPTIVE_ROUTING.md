# SHURY Company C18 — Adaptive Delegation & Load-Aware Routing

Version: `25.7.0-alpha1-company21`
Base: `25.6.0-alpha1-company20`

## Purpose

C18 makes Company delegation capacity-aware without creating a second authority or competence store.
The controller consumes already-qualified capability candidates and ranks them using capability fit,
verified organizational outcome evidence, current active workload, declared risk, and cost.

## Canonical sources

- `LearningStore.company_delegation_evidence` for verified outcome evidence.
- `LearningStore.company_projects` and `LearningStore.company_project_tasks` for active workload.
- `OrganizationRegistry` for ownership, role class, and qualification boundaries.

No new persistence store is introduced.

## Routing contract

Ownership is resolved first. A candidate is discarded if its declared department, specialist role, or
builder role cannot be proven from the OrganizationRegistry. Routing signals only rank the surviving
candidates.

The routing score is deterministic and keeps capability fit dominant. Evidence and current load are
secondary quality/capacity signals; risk and cost provide additional stable tie-breaking information.

## Recovery

After a non-governance execution/verification failure, Company Recovery may reuse the controller's
secondary ordering among already-qualified alternatives that have verified success evidence.
Authorization, approval, dependency, and context failures still escalate and never trigger adaptive
redelegation.

## Operational surface

`/company-routing <capability>` reports the current qualified routing candidates and their evidence/load
components without granting execution authority.

## Gate

C18 passes when load changes the preference only within the qualified candidate set, canonical evidence
and portfolio state are the only persistence sources, and routing cannot mutate ownership or governance.
