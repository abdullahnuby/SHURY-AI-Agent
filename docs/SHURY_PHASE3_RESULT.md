# SHURY Phase 3 — Learned Transition Model

## Status

**DONE — Phase 3 only. Phase 4+ not started.**

## Research-driven design decisions

Phase 3 uses an explicit empirical one-step dynamics model rather than a neural world model.
This follows the requested progression and is consistent with model-based RL work showing that learned transition dynamics can be represented explicitly and updated online from observed transitions. Dyna-style architectures learn a forward model from real experience and use it as a source of simulated experience; however, recent work also highlights that inaccurate learned models can compound errors when iterated for long rollouts. SHURY therefore stops at a bounded, one-step empirical model in this phase; multi-step imagination/planning belongs to later phases. 

The model maintains transition counts and outcome distributions per exact canonical state/action context. This avoids collapsing incompatible contexts and provides an evidence-based uncertainty signal. Bayesian transition-count formulations similarly maintain posterior beliefs over transition probabilities rather than replacing the previous estimate with the latest observation.

## Implemented

### 1. Persistent transition model

Added `app/learning/transition_model.py` with `LearnedTransitionModel`.

For each `(canonical_state_fingerprint, action_signature)` it stores:

- observation count
- successful observations
- verified observations
- next-state distribution
- outcome distribution
- failure-mode distribution
- mean duration + online variance accumulator
- optional observed reward statistics
- first/last observation timestamps
- model version

The implementation is deterministic/statistical and requires no neural model or LLM.

### 2. Context preservation

The primary model key is:

```text
state fingerprint + normalized action signature
```

The action signature intentionally excludes runtime identity and historical counters while preserving:

- capability
- tool
- parameters
- preconditions
- expected effects
- risk
- reversibility

Thus the same operation with different parameters remains distinguishable, while the same logical action across executions shares evidence.

### 3. Distribution instead of overwrite

If the same state/action produces:

```text
S -> S1 : 8
S -> S2 : 2
```

the model retains both outcomes.

It predicts the most-supported next state while exposing its probability and uncertainty.

### 4. Conservative confidence

Confidence is based on both:

- empirical posterior-like outcome concentration
- evidence count

A single observation cannot produce high confidence.

### 5. Online incremental updates

The model uses online mean/Welford-style accumulation for duration and optional reward observations. No historical experience is discarded when new evidence arrives.

### 6. Existing runtime integration

`WorldModel.predict()` now consults the learned transition model first when sufficient evidence exists, then falls back to the existing deterministic tool-contract prediction.

The existing governed runtime remains authoritative.

The learned model cannot:

- execute tools
- bypass policy
- bypass approval
- bypass verification
- promote skills
- modify runtime authority

### 7. Real experience feeds the model

`SelfImprovementManager.observe_run()` now feeds actual Phase-2 transitions into the learned model after recording the episode/replay evidence.

On subsequent executions, the model can retrieve the previous learned prediction before the new transition is observed.

The transition record now preserves the learned `predicted_state` when one exists.

### 8. Prediction/error boundary

The Phase-3 model exposes prediction and uncertainty but does **not** implement the formal prediction-error learning loop yet.

That remains Phase 5 as specified.

The runtime therefore does not incorrectly compare a learned state fingerprint against a `StateDiff` and label every learned prediction as a mismatch.

## Database migration

The existing `learning.db` receives a new `transition_models` table through the existing `LearningStore` schema migration path.

No second database or memory subsystem was introduced.

## Behavioral verification

Phase 3 tests cover:

1. Multiple observations aggregate instead of overwriting.
2. Stochastic next states remain represented as a distribution.
3. Different state contexts remain separate.
4. Unknown state/action pairs return no learned prediction.
5. One observation cannot create high confidence.
6. Action identity does not fragment the model, but parameter changes do.
7. Existing `WorldModel` consumes learned evidence.
8. Runtime learning creates a reusable model entry.
9. A later episode receives the previously learned predicted state.
10. Legacy Phase-2 replay and world-model behavior remain intact.

Targeted regression:

```text
45 passed
```

Compilation:

```text
python -m compileall -q app tests
```

The complete repository suite was also started; it exceeded the execution time available in this environment before completion. The targeted Phase 1/2/3, Layer-5, world-model, CLI, and acceptance suites completed successfully.

## Architecture after Phase 3

```text
REAL ENVIRONMENT
      |
      v
OBSERVED TRANSITION
      |
      +----------------------+
      |                      |
      v                      v
EXPERIENCE STORE        PRIORITIZED REPLAY
      |
      v
LEARNED TRANSITION MODEL
      |
      +------------------------------+
      |                              |
      v                              v
P(next_state | S,A)          outcome/failure distributions
      |
      v
confidence / uncertainty
      |
      v
WORLD MODEL PREDICTION
      |
      v
GOVERNED RUNTIME
```

## Explicitly NOT implemented

- Reward/value model — Phase 4
- Formal prediction-error update — Phase 5
- Counterfactual simulator — Phase 6
- Model-based planner — Phase 7
- Exploration/information gain — Phase 8
- Continual-learning invalidation/consolidation — later phases

## Core result

SHURY now has a real persistent empirical transition model that changes as verified runtime experience accumulates. It no longer treats the deterministic tool contract as its only source of consequence prediction.

It still does **not** claim full model-based intelligence: the learned model must next be connected to reward/value learning and formal prediction-error updates before it can drive model-based planning.
