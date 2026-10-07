# SHURY Company 19 — C16 Controlled Company Learning Loop

Version: `25.5.0-alpha1-company19`
Base: `25.4.0-alpha2-company18`

## Scope

C16 only. No C17+ work was started. No LLM fallback was added and `omarelshehy/Arabic-Retrieval-v1.0` was not replaced.

## 1. Verified post-change learning

Before: Apply only changed lifecycle state and stored a monitoring baseline.
After: monitored Company changes accept canonical post-change outcomes with a canonical task signature, verify specialist/department/tool contracts, write verified outcomes to canonical Company Memory, and update canonical specialist reliability in `LearningStore.company_delegation_evidence`.

## 2. Unseen-task generalization

Before: monitoring compared only the general Company evaluation and skill aggregate rates.
After: verification-case signatures are persisted in regression evidence. Post-change outcomes that match a verification case are rejected as unseen evidence; structurally independent runtime task signatures are measured separately as generalization evidence.

## 3. Regression detection and governed rollback proposal

Before: monitor returned a comparison only; it could not open a rollback proposal.
After: monitoring returns `keep` or `recommend_rollback`. A failed generalization/governance gate opens one `skill_rollback` proposal in the canonical Company proposal ledger and never mutates the Skill automatically.

## 4. Organization-level improvement

Before: post-change monitoring had no organization-level reliability metric.
After: monitoring snapshots aggregate Company specialist reliability separately from the single changed skill and requires organization-level non-regression for retention.

## Runtime surface

Added `/company-change-monitor <proposal_id>` for the C16 monitoring path. Existing C15 governance commands remain otherwise unchanged.

## Gate

A monitored change is retained only when verified unseen-task evidence demonstrates improvement relative to the relevant capability baseline and Company governance limits remain satisfied. Otherwise the system recommends rollback and, for Skill changes, opens a governed rollback proposal without applying it.
