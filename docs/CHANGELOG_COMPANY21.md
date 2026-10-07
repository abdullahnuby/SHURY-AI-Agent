# SHURY Company 21 — C18 Adaptive Delegation & Load-Aware Routing

Version: `25.7.0-alpha1-company21`
Base: `25.6.0-alpha1-company20`

## C16 pending-issue status

The CLI governance integration issue was already closed before C17 and remains green.

## C18 changes

### Adaptive routing controller
Before: Company team/recovery selection did not have a reusable load-aware routing component.
After: `AdaptiveDelegationController` ranks only already-qualified candidates using structured capability
fit, canonical verified evidence, current active workload, declared risk, and cost.

### Portfolio load as canonical evidence
Before: C14 exposed specialist workload but team/recovery routing did not consume it as a reusable
secondary routing signal.
After: C18 reads active project/task assignments from the canonical `LearningStore` and penalizes
higher active load deterministically.

### Recovery integration
Before: recovery alternatives were ranked only by fit, success evidence, and cost.
After: the same controller provides a secondary capacity-aware ordering after those existing eligibility
checks; governance/context failures remain escalation-only.

### Generic operational inspection
Added `/company-routing <capability>`; it reports routing factors only and grants no authority.

## Boundaries

- No LLM fallback.
- `Arabic-Retrieval-v1.0` unchanged.
- No second learning/competency store.
- No sentence- or operation-name-specific routing.
- Ownership and authority remain immutable.

## Verification

The release report contains the exact C18, Company, organization core, Layer-5, lifecycle, hardening,
CLI, source compile, and runtime-artifact results.
