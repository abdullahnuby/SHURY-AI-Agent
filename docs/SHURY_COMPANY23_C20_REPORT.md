# SHURY Company 23 — C20 Learning Integrity Report

Version: `25.9.0-alpha1-company23`
Base: `25.8.0-alpha1-company22`

## Conclusion

C20 proves that SHURY's model-based policy can be driven by learned parameters rather than a fixed operation-name rule or fixed final scoring recipe, once sufficient runtime evidence exists.

Important distinction: `Arabic-Retrieval-v1.0` remains a frozen retrieval model in the runtime. SHURY does **not** fine-tune that embedding model online. The online learning parameters are the canonical tabular transition model, TD(lambda)/SARSA state-action values, prediction-error statistics, UCB bandit evidence, and meta-strategy observations.

## Findings and action

### 1. Evidence already present

`SelfImprovementManager.observe_run()` records real trajectories and then performs:

`experience → replay → world_model_update → value_update → policy_update → prediction error → exploration/bandit feedback`

The canonical `LearningStore` persists the resulting state/action values and transition evidence.

### 2. Gap found

`ModelBasedPlanner._evaluate_plan()` combined learned predictions with a fixed hand-written numeric heuristic. This meant learned values influenced behavior but did not always own the final policy decision.

### 3. C20 correction

After every action in a candidate sequence has at least two observed action-value visits, the planner switches its final policy basis to the learned action values. The old heuristic is retained only for cold-start candidates without sufficient policy evidence.

### 4. Behavioral proof

A deterministic two-action experiment with arbitrary names first trained one action as better, then reversed the outcome regime. The selected plan changed from the first action to the second, while no action name is referenced in the policy code.

Observed example from the audit:

- phase 1: `A` chosen; Q(A)=0.6531, Q(B)=0.0347
- after environment reversal: `B` chosen; Q(A)=0.1633, Q(B)=0.6600

The transition model probabilities became less decisive after the regime reversal, while the learned value estimates still changed enough to reverse policy choice.

### 5. Exploration proof

A 120-trial feedback experiment selected the empirically better action `A` 113 times; the last 40 selections contained 39 `A` selections. A separate 200-trial non-stationary bandit test is included in the regression suite.

This demonstrates bounded exploration/exploitation, not a mathematical guarantee of global optimality. SHURY can only optimize within the candidate action set and evidence it can observe.

## Regression results

Company + core + Layer-5 + lifecycle + weight-driven tests:

```text
142 passed in 20.09s
```

Source compile and runtime artifact gates were also run on the release build.

## Baseline proof

The same new weight-driven test file run against Company 22 produced:

```text
2 failed, 2 passed
```

The failures were specifically the new selection-basis contract, which did not exist in C19.

## Known verification blocker

The current execution container does not have `sentence_transformers` installed and has no network access to install it. A direct live `CognitiveKernel.act()` attempt therefore fails at the Arabic retrieval dependency boundary. Existing hermetic tests intentionally set `SHURY_NLP_MODE=off` and continue to verify the downstream learning/runtime contracts. No test or code path was changed to conceal this blocker.

## Scope discipline

C20 changed only the model-based final policy selection and the associated regression evidence. It did not add an LLM, replace the Arabic model, create a second learning store, alter governance authority, or change ownership contracts.
