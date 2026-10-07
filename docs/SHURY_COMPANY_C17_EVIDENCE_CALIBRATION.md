# SHURY Company C17 — Evidence-Calibrated Workforce

C17 converts canonical runtime delegation outcomes into conservative competency profiles.

## Source of truth

The only learning evidence source is `LearningStore.company_delegation_evidence`. C17 does not create a competency database.

## Calibration

For each capability/specialist/tool tuple, C17 exposes:

- attempts
- verified successes/failures
- observed success rate
- 95% Wilson lower confidence bound
- evidence state

A small number of observations is explicitly marked `insufficient_evidence`.

## Team formation

Calibrated evidence is blended into the pre-existing history score only when a matching organization evidence row exists. Capability coverage, structured ownership, and minimum specialist count remain primary decisions.

C17 cannot change:

- organization ownership
- role authority
- reviewer independence
- SkillBank trust/status
- approval or rollback state

## Runtime

`/company-competency [capability]|[specialist]` reports current calibration from the canonical LearningStore.
