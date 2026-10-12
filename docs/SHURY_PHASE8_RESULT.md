# SHURY Phase 8 — Exploration / Information Gain

## Objective

Convert learned uncertainty into explicit, bounded exploration and information-seeking behavior without granting learning execution authority. The architecture follows the project specification: safe exploration is a policy signal for deciding what information is worth acquiring, not permission to bypass runtime controls.

## Implementation

### Exploration policy

`app/learning/exploration.py` provides `ExplorationPolicy` and `build_exploration_actions`. The score combines: goal alignment, observed utility, UCB-style epistemic optimism, Bayesian one-step information gain, novelty, historical prediction-error pressure, risk and cost.

The information-gain estimate uses a small symmetric Dirichlet prior with an explicit unseen outcome bucket. As evidence accumulates, expected uncertainty reduction falls. This is consistent with Bayesian active exploration work that uses model uncertainty/novelty as an information-acquisition objective rather than treating random action as exploration.

### Candidate expansion

Earlier exploration was circular because it could only see actions already returned by deterministic planning. Phase 8 expands candidates from the explicit registry, but only when: the tool opts into exploration, risk is low, no approval is required, it is idempotent, it has no world delta/resource side effect, and deterministic argument validation succeeds.

### Information-first behavior

A safe information action can now displace an uncertain direct action. For an unconstrained learning request, contract-declared local evidence probes are evaluated before paying for external research; an explicit web/internet request remains a hard source constraint. After that observation, the kernel performs one exploitation-only replan (`allow_exploration=False`) so the same decision cycle does not oscillate between information tools.

### Learning boundary

Exploration decisions themselves do not create synthetic transitions or value updates. Only governed real execution and verification feed Phase 2–5 learning.

## Research basis

- UCB-style exploration balances estimated utility with uncertainty.
- Active Bayesian model-based exploration uses information gathering / novelty to improve the learned model.
- Safe Bayesian exploration keeps safety constraints active during learning.
- Recent 2026 information-gain work shows that explicit information bonuses can be integrated with non-black-box uncertainty estimation, supporting the decision to keep Phase 8 statistical and inspectable rather than introducing a neural network.

## Behavioral gate

`tests/test_phase8_exploration.py` verifies:

1. information gain falls as evidence accumulates;
2. an unseen safe action can be selected by epistemic optimism;
3. unsafe actions are excluded;
4. deterministic seeded arguments are preserved;
5. `learn from web ...` retains the actual topic;
6. learning requests can take an information-first step;
7. one information step is followed by a direct/research replan without oscillation.

`scripts/phase8_exploration_demo.py` is a local reproducible demonstration of the cold-start and evidence-accumulation behavior.

## Limits

Phase 8 does not implement continual-learning decay, broad procedure generalization, meta-strategy learning, self-model integration, or dynamic model invalidation. It also does not allow arbitrary unknown actions: exploration remains constrained by explicit safe tool contracts.
