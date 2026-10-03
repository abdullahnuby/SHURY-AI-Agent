# SHURY Phase 4 — Reward and Value Learning

## Status

**DONE — Phase 4 implemented and regression-tested.**

Phase 4 builds directly on the Phase-3 empirical transition model. It turns verified runtime
outcomes into an explicit learning signal and learns persistent state/action continuation value
from real trajectories.

## Research basis

The design follows the standard reinforcement-learning separation between observed rewards,
value prediction, and later control/planning. Temporal-difference methods learn value from real
experience by bootstrapping from subsequent value estimates, while eligibility traces provide a
mechanism for assigning delayed outcomes to earlier decisions. The classic Dyna/Q-learning
formulation also treats the transition model as separate from direct value learning and planning.
Recent continual-RL work emphasizes the need to retain and update knowledge across changing
experience streams, while recent work on temporal credit assignment continues to identify delayed
and sparse feedback as a central difficulty.

Primary references used for this phase:

- Sutton & Barto, *Reinforcement Learning: An Introduction* — TD learning, eligibility traces,
  and tabular value/control methods.
- Javed, Sharifnassab & Sutton (2024), *SwiftTD* — modern work on robust temporal-difference
  learning and credit assignment.
- Pan et al. (2025), *A Survey of Continual Reinforcement Learning* — continual adaptation and
  retention of learned knowledge.
- Pignatelli et al. (2023), *A Survey of Temporal Credit Assignment in Deep Reinforcement
  Learning* — delayed/noisy outcome attribution and credit-assignment failure modes.

## Implemented

### 1. Explicit reward model

Added `app/learning/value_model.py` with `RewardModel`.

The reward signal is constructed only from evidence already recorded by the governed runtime:

- verified success
- unverified success
- failure
- retry count
- episode-level completion reward

Each transition stores:

- `reward`
- reward source
- confidence
- local step contribution
- terminal contribution
- named reward components

The episode reward remains the task-level score. The transition reward is a bounded learning
signal; it is not presented as ground-truth human utility.

No LLM judge is used to assign reward.

### 2. Persistent state-value learning

`ValueModel` learns a tabular value for each exact state fingerprint.

The update is an accumulating-trace TD(lambda) backup over observed trajectories:

```text
δt = r_t + γ V(s_{t+1}) - V(s_t)
trace(s_t) += 1
V(s) += α δt trace(s)
trace(s) *= γ λ
```

This gives delayed terminal outcomes backward credit without generating imagined states or
executing counterfactual tools.

### 3. Persistent behavioral action values

Phase 4 also learns a state/action value using the **observed continuation** (SARSA-style):

```text
Q(s_t,a_t) <- observed reward + γ Q(s_{t+1},a_{t+1})
```

This is intentionally a behavioral continuation-value estimate, **not an optimal Q-function**.
There is no `max_a`, policy-gradient update, exploration policy, or automatic action selection.
The learned values are advisory data for later planning/control phases.

### 4. Empirical return statistics

Every learned state/action value also retains running Monte-Carlo return statistics:

- visit count
- return mean
- online variance accumulator
- model version
- timestamps

`ValuePrediction` exposes:

- value
- empirical return mean/std
- confidence
- uncertainty
- visit count

Confidence is evidence-aware; one observation does not imply certainty.

### 5. Existing database extended

The existing `learning.db` is extended with:

- `state_values`
- `action_values`

No second learning database or new memory subsystem was introduced.

### 6. Runtime learning loop integration

`SelfImprovementManager.observe_run()` now executes this evidence flow:

```text
verified runtime trajectory
        ↓
experience record + replay
        ↓
Phase-3 transition model
        ↓
Phase-4 reward annotation
        ↓
Phase-4 TD(lambda) value learning
        ↓
persistent state/action value tables
```

The normal runtime remains authoritative. Value learning cannot execute tools, bypass policy,
change approval, bypass verification, promote skills, or alter runtime permissions.

## Deliberate boundaries

Phase 4 does **not** implement:

- formal world-model prediction error learning — Phase 5
- counterfactual transition simulation — Phase 6
- model-based search/planning — Phase 7
- exploration/information gain — Phase 8
- neural/generalizing value approximation
- automatic policy updates

The exact-state tabular representation is intentional. It avoids inventing generalization across
states that SHURY has not established as equivalent. Generalization can be introduced later only
with explicit evidence and evaluation.

## Verification

New tests in `tests/test_phase4_value_learning.py` cover:

1. Evidence-based reward construction and terminal-goal separation.
2. Negative terminal learning signal for failed episodes.
3. Delayed reward credit assignment through TD(lambda).
4. Separation of good and failed action values in the same state.
5. Persistence, uncertainty, and inspectable action estimates.

Regression suite used for the phase:

```text
53 passed in 0.54s
```

Compilation:

```text
python -m compileall -q app tests
```

The full repository suite is intentionally not reported as passed here because an earlier full
run exceeded the available execution window before completion.

## Result

After Phase 4, SHURY has a second persistent learning layer above the Phase-3 world model:

```text
REAL EXPERIENCE
      ↓
Transition Model (Phase 3)
      ↓
Observed Reward Signal (Phase 4)
      ↓
Value Learning
  ├─ V(state)
  └─ Q_behavior(state, action)
      ↓
confidence / uncertainty / return statistics
      ↓
Future planning/control phases
```

SHURY can now learn not only **what tends to happen after an action**, but also **how valuable an
observed state and behaviorally observed action continuation has been**, while keeping execution
authority outside the learning subsystem.
