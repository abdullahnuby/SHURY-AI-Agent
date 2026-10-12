# SHURY — Specification Gap Closure

The numbered production roadmap remains the canonical Phase 0–14 roadmap from the engineering migration specification. Missing proof/features are tracked here as G-IDs so the original phase numbering is not rewritten.

## G01 — Model Invalidation / Drift
Status: DONE + verified
- prediction-error spike detection
- outcome distribution shift detection
- success-rate degradation detection
- stale transition marking
- automatic exploration pressure increase
- fresh-evidence relearning
- stale procedure invalidation when a dependent runtime tool drifts

Proof: `tests/test_model_invalidation.py`

## G02 — Meta-Strategy Controller
Status: DONE + verified
- strategy families: direct, sequential, search, exploration, verification-first, information-first, recovery-first
- state type → preferred strategy evidence
- persistent observations
- planner-facing selection evidence

## G03 — Structured Procedural Memory + Generalization
Status: DONE + verified
- trigger conditions
- termination conditions
- recovery strategy
- context boundary
- task-family signatures
- persistent procedure evidence and versions
- legacy `procedure_priors` migration only; no new writes

Remaining proof hardening: aggregate two value-slot instances into one canonical family record in a dedicated acceptance test.

## G04 — Failure + Recovery Learning
Status: DONE + verified
- root transition diagnosis
- expected-vs-unexpected failure
- alternative-action evidence
- recovery candidate generation
- bounded simulation before selection
- recovery-quality learning
- repeated verified recovery promotion

## G05 — Evaluation Proofs
Status: DONE + verified
- multi-dimensional reward evidence
- non-stationary bandit with change detection
- information-gain decision proof
- context-specific self-model influence
- A→B→C credit assignment
- catastrophic-forgetting measurement
- transfer/regression/learning-speed/exploration-efficiency/action-selection metrics

## G06 — Causal Learning
Status: DONE + verified
- observational association kept separate from causal effect
- matched-state controlled effect
- explicit confounding risk
- model-only counterfactual replay
- persistence of causal estimates
- zero runtime side effects during counterfactual replay

## G07 — Architecture Boundary Closure
Status: DONE + verified
- one canonical `LearningStore`
- `app/brain/learning.py` is compatibility alias
- `BrainKnowledgeStore` is facade over canonical learning DB
- legacy `brain.db` is migration source only
- `run_cognitive` = Language Gateway → Structured Goal → canonical Brain
- LLM cannot choose tools or execute actions on canonical path
- legacy LLM ReAct is an explicit opt-in adapter only
- `/react` remains benchmark/experimentation surface, not cognitive fallback

## Gate policy

A G-ID is not considered complete because code exists. It is complete only when:
1. the capability is reachable from the correct architectural layer;
2. persistence/concurrency contracts are respected;
3. a focused acceptance test proves the behavior;
4. phase regression remains green.

### G03 proof hardening — completed 2026-10-01
- Added a dedicated acceptance test proving `calculate 20+30` and `calculate 40+50` share one canonical task-family procedure record.
- Verified evidence from both runs is retained and the shared family promotes/retrieves after repeated verified success.


## G09.x — Integration / Release Boundary
Status: IN PROGRESS
- canonical State + Learning persistence unification
- legacy brain-state migration with test isolation
- explicit legacy LLM test boundary
- canonical regression and clean release packaging
