# SHURY Behavioral Learning Gate — X/Y Reversal

## Purpose

This experiment verifies **behavior change**, not merely data accumulation.
It presents two learned actions from the same state:

- Regime A: X succeeds on 8/10 observations, Y on 2/10.
- Regime B: X succeeds on 2/10 observations, Y on 8/10.

The planner must select X after Regime A and Y after Regime B.

The experiment is deterministic in its observation schedule so the result is reproducible. The observations still enter the normal transition and value learning APIs; no planner preference is hardcoded.

## Run

```bash
pytest -q tests/test_behavioral_learning_xy.py
```

## Interpretation

Passing the gate demonstrates that the current learned value/transition stack can change action selection after the observed outcome regime reverses. It does **not** prove Phase 8 exploration, nor does it prove dynamic model invalidation under arbitrary distribution shift.
