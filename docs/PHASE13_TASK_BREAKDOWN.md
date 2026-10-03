# SHURY Phase 13 — Language Pattern Caching

## Objective
Reduce unnecessary dependence on the language model without moving intelligence into the model layer.

## Safety boundary
A cached mapping may only be used as a semantic-perception optimization. It never selects tools, executes actions, changes permissions, or bypasses Brain/runtime validation.

## Promotion rule
A pattern starts as `candidate` evidence. It becomes `promoted` only after repeated verified successful uses (default: 3) with high semantic confidence (>= 0.82), no failed uses, and no contradictory mapping for the same pattern.

## Cache eligibility
Phase 13 initially caches only static language patterns. Requests containing dynamic slots/entities/references/temporal constraints, fresh-data requirements, ambiguity, safety signals, or low confidence remain on the normal semantic path.

## Runtime path
`Human text -> deterministic semantic parse -> promoted pattern lookup -> LLM only when still needed -> canonical Brain`

A cache miss is not a failure; it simply continues to the existing language/model path.

## Persistence
Pattern observations and mapping aggregates live in the existing `LearningStore` database. The cache does not introduce a second database architecture.

## Verification
- Single use does not promote.
- Three verified uses promote.
- Failed evidence revokes the mapping and prevents promotion.
- Contradictory mapping revokes the prior promoted mapping.
- Dynamic/uncertain requests are excluded.
- A promoted mapping can bypass the model when semantic fallback would otherwise require it.
- Regressions for Phases 2–13 and V23 remain green.
