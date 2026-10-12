# SHURY Phase 7 — Model-Based Planning

## Purpose

Phase 7 adds a bounded model-based planner that searches over **empirically observed state/action edges**, uses the Phase-6 counterfactual simulator to evaluate candidate sequences, and produces an ordinary `Plan` that remains subject to the existing deterministic validation/certification path.

It does **not** execute tools, mutate learning data, train a policy, or invent unsupported transitions.

## Research basis

The design follows the Dyna family of architectures: a learned world model can support planning/search over simulated experience, while the resulting plan remains distinct from real execution. Sutton & Barto describe search control as selecting experienced state/action pairs and emphasize that planning can use probabilistic and imperfect learned models. See:

- https://incompleteideas.net/book/bookdraft2018mar21.pdf
- https://incompleteideas.net/publications.html

Recent model-based planning work also supports combining learned models with search and explicitly accounting for model uncertainty. Examples reviewed for this phase include:

- Bayes Adaptive Monte Carlo Tree Search for model-based RL: https://arxiv.org/abs/2410.11234
- WorldPlanner: https://arxiv.org/abs/2511.03077
- Safe Planning and Policy Optimization via World Model Learning: https://arxiv.org/abs/2506.04828
- Learning from World Feedback: Why Model Uncertainty Fails as a Risk Signal in Model-Based RL: https://arxiv.org/abs/2607.16591
- Uncertainty-driven trajectory truncation: https://arxiv.org/abs/2304.04660

The last two results motivate an important SHURY boundary: internal model uncertainty is treated as a planning-quality signal, **not as a replacement for externally verified task risk**.

## Implementation

### `app/planning/model_based_planner.py`

Introduces:

- `ModelBasedPlanner`
- `ModelPlanEvaluation`
- `ModelPlanCandidate`

Algorithm: **risk-aware bounded model-based beam search**.

The search:

1. Starts from the exact current state fingerprint.
2. Retrieves only actions observed from that exact state by the Phase-3 transition model.
3. Rejects unknown tools, invalid learned arguments, simulation-recursion actions, and root-level contract violations.
4. Expands empirical next-state distributions while carrying branch probability and accumulated uncertainty.
5. Tracks progress against parsed goal clauses, including explicit `then` ordering.
6. Uses the Phase-4 state/action values as heuristic/value evidence.
7. Stops when the configured depth/search/uncertainty limits are reached.
8. Re-evaluates complete candidate sequences with Phase-6 `CounterfactualSimulator`.
9. Computes a composite model-planning score from goal completion, expected return, terminal value, behavioral value, expected success, confidence, uncertainty, truncation/unsupported mass, risk, cost, and duration.
10. Runs the normal `validate()` + `certify_plan()` gates before returning a plan.

### `app/learning/store.py`

Added a read-only `actions_for_state()` query so search control can enumerate actions already grounded in the learned transition graph.

### `app/learning/transition_model.py`

Exposes `actions_for_state()` as the public transition-model API.

### `app/planning/planner.py`

Added an explicit `RulePlanner.model_based_plan()` entry point. The normal `RulePlanner.plan()` behavior is unchanged; Phase 7 is opt-in until a later control phase defines arbitration between deterministic planning and model-based search.

## Safety / authority boundaries

The planner is not an execution authority.

- No tool function is called during planning.
- No learning record is created or updated.
- No prediction-error record is created during planning.
- No simulated transition is promoted to real experience.
- No unsupported state/action edge is fabricated.
- Final plans still pass deterministic certification.
- Tool approval requirements remain part of the existing runtime path.

## Known limitation

Phase 3 intentionally keys the learned model by **exact state fingerprint + exact action signature**. Phase 7 therefore searches a learned graph, but it does not generalize across semantically similar states. That restriction is deliberate: generalization without a validated representation would allow unsupported transitions into the planning graph.

A future representation-learning/generalization phase can relax this boundary only with explicit validation and out-of-distribution controls.

## Not implemented in Phase 7

- online policy optimization
- actor/critic training
- model-generated learning updates
- unrestricted imagination
- open-world action generation
- LLM-generated transition guesses
- automatic execution of the selected plan

Those require separate authority and evaluation boundaries.
