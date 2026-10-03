# SHURY Phase 10 — Online Learning Loop

## Goal

Phase 10 closes the real execution-to-learning loop in the existing `SelfImprovementManager` without creating a second orchestration engine.

The cycle is:

`REAL EXECUTION -> REWARD -> PREDICTION ERROR -> IMMUTABLE EXPERIENCE -> REPLAY INDEX -> WORLD MODEL -> VALUE/POLICY EVIDENCE -> PROCEDURAL MEMORY -> LESSON/SKILL UPDATE -> SELF-MODEL REFRESH`

## Implementation

### Durable learning-cycle ledger

`LearningStore` now owns two additional tables:

- `learning_cycles`: one row per execution learning cycle.
- `learning_updates`: one row per named learning stage for that execution.

Stages are persisted in execution order and expose `running`, `completed`, and `failed` status.

### Duplicate protection

A completed `run_id` is treated as already learned. Re-observing the same run returns a duplicate learning result and does not re-apply the transition/value updates.

### Real-evidence ordering

The existing execution trajectory is scored before it is used to update the learned transition model. Prediction error therefore compares the prior model against the actual outcome rather than evaluating a model after it has already seen that outcome.

### Policy evidence

The existing action-value learner is the canonical policy evidence for this phase. Phase 10 does not create a second policy subsystem. `Q(state, action)` updates are recorded as the policy-learning stage and are available to the existing planners.

### Procedure/lesson learning

Verified runtime trajectories continue to feed the existing `BrainKnowledgeStore`. Lesson and skill-candidate creation remain governed by repeated evidence and existing promotion gates.

### Self-model

After the learning cycle, the canonical Brain refreshes its observed capability reliability snapshot. The cycle records that refresh as a durable stage.

## Boundaries

- No LLM is used by the learning loop.
- No counterfactual/synthetic trajectory is promoted to real evidence.
- No learning component gets execution authority.
- No new memory database is created.
- No second planner is created.
- Phase 11 replay training is not implemented here; Phase 10 only indexes real transitions into the existing replay substrate.
- Crash-atomic multi-table learning transactions remain a production-hardening concern because the current model components expose separate persistence methods.

## Research rationale

Continual RL assumes non-stationarity can occur in deployed environments; maintaining an explicit cycle and preserving historical evidence makes the adaptation path inspectable. Recent 2025/2026 work also emphasizes the tension between adaptation, catastrophic forgetting, and safety, supporting a conservative online-update design.
