# SHURY Phase 6 — Counterfactual Simulation

## Status

**DONE — bounded, uncertainty-aware, read-only counterfactual simulation.**

## Research-driven design

Phase 6 introduces model-based counterfactual rollouts on top of the empirical transition model from Phase 3, the learned value model from Phase 4, and prediction-error feedback from Phase 5.

Dyna-style systems use a learned model to generate simulated experience for planning, but the literature also highlights that model errors accumulate through multi-step rollouts. Recent work proposes tracking uncertainty/error during rollouts and terminating when the model becomes unreliable. SHURY therefore uses short finite horizons, exact learned state/action support, branch limits, probability pruning, and an accumulated-uncertainty cutoff rather than unrestricted imagination.

References used for the design:

- Sutton & Barto, *Reinforcement Learning: An Introduction*, Dyna chapter: simulated experience should come from the learned model and can be interleaved with learning/planning. https://incompleteideas.net/book/bookdraft2018mar21.pdf
- Frauenknecht et al., *On Rollouts in Model-Based Reinforcement Learning* (2025): model error can accumulate in rollouts; uncertainty/error-aware termination is important. https://arxiv.org/abs/2501.16918
- Frauenknecht et al., *Trust the Model Where It Trusts Itself* (2024): model trust should depend on local uncertainty rather than assuming uniform accuracy. https://arxiv.org/abs/2405.19014
- Webster & Flach, *Risk Sensitive Model-Based Reinforcement Learning using Uncertainty Guided Planning*: uncertainty can be used to avoid poorly supported simulated regions. https://arxiv.org/abs/2111.04972

## Implemented

### 1. `CounterfactualSimulator`

Added `app/world/counterfactual.py`.

The simulator:

- starts from a real `WorldState` fingerprint or an explicit state signature;
- consumes a fixed sequence of candidate actions;
- branches over the learned next-state distribution;
- propagates probability mass through the rollout;
- attaches predicted reward, duration, success/verification probabilities, value estimates, confidence and uncertainty;
- truncates unsupported or unreliable branches;
- caps rollout depth and branch count;
- never calls a tool.

### 2. Exact support only

The simulator calls `LearnedTransitionModel.predict()` for each `(state, action)`.

Unknown contexts are not filled with an LLM guess, a random state, or a deterministic invented state. They terminate the counterfactual as `unknown_state_action`.

### 3. No synthetic learning contamination

Counterfactual branches remain transient.

Simulation does **not**:

- call `learn_transition()`;
- update prediction-error records;
- update replay;
- update TD values;
- mutate the real `WorldState`;
- execute any tool.

This keeps imagined evidence separate from real evidence. Dyna-style planning can later consume simulated experience, but Phase 6 intentionally stops before that control/learning integration.

### 4. Uncertainty-aware rollout termination

A branch is stopped when:

- no empirical transition exists;
- model confidence is below the minimum threshold;
- accumulated uncertainty reaches the configured safety bound;
- all available next-state branches fall below the probability floor;
- the configured horizon is reached.

The accumulated uncertainty uses a conservative bounded composition of per-step model uncertainty. This is a simulation-control heuristic, not a calibrated probability claim.

### 5. Stochastic branches

The current Phase 3 model stores marginal next-state, outcome and reward evidence. Phase 6 therefore does not invent a joint next-state/outcome distribution.

A branch represents a next-state probability from empirical transition evidence; predicted reward remains the learned expected reward for that context. The result explicitly notes this limitation.

### 6. Value annotations

When Phase 4 has a learned value for the predicted state, the simulator attaches:

- terminal state value;
- value confidence;
- branch discounted return.

The simulator does not update the value model.

### 7. Alternative simulations

`simulate_alternatives()` runs multiple candidate sequences independently from the same initial state.

It deliberately does **not** rank, choose, or recommend one sequence. Candidate selection belongs to Phase 7 planning.

### 8. System tool

Added `simulate_counterfactual` under `app/tools/system/counterfactual.py`.

Input:

```json
{
  "actions": [
    {"tool": "tool_a", "args": {}},
    {"tool": "tool_b", "args": {}}
  ]
}
```

The tool resolves real tool contracts and builds the same semantic action representation used by the learned model.

Nested simulation tools are rejected.

## Boundaries

Phase 6 does **not** implement:

- policy optimization;
- automatic action selection;
- MCTS or tree search;
- Dyna value updates from imagined transitions;
- exploration strategy;
- long-horizon unrestricted world generation;
- neural/world-model generalization beyond exact empirical contexts.

These remain future phases.
