# SHURY Phase 5 — Prediction Error, Surprise & Calibration

## Status

**DONE — Phase 5 implemented and regression-tested.**

Phase 5 closes the prediction/error boundary left intentionally open in Phase 3. A learned
transition is now evaluated against the **actual subsequent runtime observation before the
current observation is added to the model**. The resulting error is persisted, aggregated, fed
back into future model confidence, and exposed to the governed runtime as structured evidence.

## Research basis

The design uses established ideas from reinforcement learning and probabilistic prediction:

- Model-based RL work measures world-model error by comparing predicted dynamics with observed
  transitions; value-aware model error can also measure the downstream effect on value estimates.
- Recent continual-RL/world-model work uses online model residuals as a signal for detecting
  unexpected environment changes and triggering adaptation.
- Uncertainty-aware TD research reinforces that prediction error should be treated as an
  uncertainty-sensitive signal rather than a single unquestioned scalar.
- Proper probabilistic scoring uses quantities such as Brier score and log loss, while
  reliability/calibration analysis compares predicted confidence with observed frequencies.

References used during implementation:

- *Mind the Model, Not the Agent: The Primacy Bias in Model-Based RL* (2023), including explicit
  definitions of model mean-squared error and value-aware model error.
- *Generalized Gaussian Temporal Difference Error for Uncertainty-aware Reinforcement Learning*
  (2024), on uncertainty-aware treatment of TD errors.
- *Continual Reinforcement Learning by Planning with Online World Models* (2025), on online world
  models and continual adaptation.
- *Self-adapting Robotic Agents through Online Continual Reinforcement Learning with World Model
  Feedback* (2026), using prediction residuals as an adaptation/OOD signal.
- Calibration literature covering Brier/log loss and expected calibration error (ECE).

## Implemented

### 1. Formal prediction-error record

Added `app/learning/prediction_error.py` with `PredictionErrorModel` and `PredictionError`.

For each prediction with sufficient learned evidence, the scorer records:

- observed next-state probability
- state log loss
- multiclass state Brier error
- success-probability Brier error
- verified-probability Brier error
- outcome log loss
- normalized duration error
- reward prediction error when reward evidence exists
- optional value-aware error when both predicted and observed state values exist
- total bounded prediction error
- confidence-weighted surprise
- prediction confidence / uncertainty
- evidence count

### 2. Leakage-safe ordering

The learning order is now:

```text
previous learned model
        ↓
produce prediction
        ↓
observe actual runtime transition
        ↓
score prediction error
        ↓
persist prediction error
        ↓
feed error statistics back into model confidence
        ↓
learn current transition
        ↓
Phase-4 reward/value update
```

The current observation is therefore not allowed to improve the prediction that is being scored.

### 3. Distributional next-state prediction

`TransitionPrediction` now exposes the learned next-state distribution, not only the most likely
state. This enables proper categorical scoring instead of a crude hit/miss check.

### 4. Error feedback into the world model

`transition_models` now retains online prediction-error statistics:

- prediction count
- mean prediction error
- error variance accumulator
- last prediction error
- last prediction timestamp

Future prediction confidence is reduced when a state/action context has accumulated systematic
prediction error. The adjustment is bounded so early errors do not completely suppress a useful
model.

### 5. Calibration analysis

`PredictionErrorModel.calibration()` computes reliability data and ECE-style calibration error
for:

- next-state top prediction
- success probability
- verification probability

This distinguishes model accuracy from model confidence.

### 6. Runtime surprise feedback

The ReAct runtime now exposes the immediate formal prediction error of learned world-model
predictions after an action result. The envelope is observational only; it cannot execute tools,
bypass policy, or change authorization.

### 7. Replay integration

Because prediction error is now attached to the transition **before** replay indexing, the existing
Phase-2 prioritized replay automatically receives a real prediction-error component rather than
always seeing zero for learned-model events.

### 8. Action-identity robustness

The learned action signature now normalizes both dictionary and serialized key/value-list forms of
`parameters`. This fixes a real serialization mismatch between historical records and runtime
world-model requests without weakening action identity.

### 9. Persistence

The existing `learning.db` is extended with a `prediction_errors` table and additional columns on
`transition_models`. No new database or parallel memory subsystem was introduced.

## Boundaries preserved

Phase 5 still does **not** implement:

- imagined/counterfactual trajectory execution
- model-based search or planning
- exploration policy updates
- automatic policy optimization
- unrestricted state generalization

Those remain later phases.

## Verification

Phase 1/2/3/4 + Phase 5 + world model + Layer 5 + CLI + V23 regression:

```text
64 passed
```

Compilation:

```text
python -m compileall -q app tests
```

The complete repository suite was started but did not finish inside the available execution window.
The remaining reported failures are outside Phase 5 and are existing repository issues, notably:

- seed scenario DB: `no such table: scenarios`
- task planning release-readiness expectation returning an empty plan

Those were not counted as Phase-5 verification failures.

## Result

SHURY now has the missing closed loop between **prediction and reality**:

```text
REAL EXPERIENCE
      ↓
Phase 3 transition prediction
      ↓
ACTUAL OBSERVATION
      ↓
Phase 5 prediction error
  ├─ accuracy
  ├─ surprise
  ├─ calibration
  └─ value-aware mismatch
      ↓
model confidence feedback
      ↓
Phase 2 replay priority
      ↓
Phase 4 value learning
```

The important architectural result is that SHURY can now distinguish:

**"the model predicted this"**

from

**"this is what actually happened"**

and preserve that discrepancy as durable learning evidence.
