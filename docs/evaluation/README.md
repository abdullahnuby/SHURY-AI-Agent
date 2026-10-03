# Layer 6 — Evaluation Lab

The evaluation lab is the release measurement system for the agent. It evaluates complete trajectories rather than only final text and combines deterministic scoring with optional calibrated model judging.

## Evaluation dimensions

- outcome / completion
- tool selection and ordering
- verification rate
- efficiency
- world-state correctness
- safety and workspace frame-condition
- repeated-trial reproducibility
- long-horizon prefix survival
- failure-pattern attribution

## Scenario packs

Scenarios are JSON-serializable and can be versioned as test data. A scenario can define expected status, required/forbidden tools, ordering, budgets, workspace fixtures, and allowed paths.

## Repetition

Use repeated runs when model behavior is stochastic. `pass_at_n` means at least one successful run; `all_n` is the strict consistency measure. Release gates should normally use `all_n` for critical tasks.

## Baseline regression

Compare a candidate report against a pinned baseline. A release is blocked when scenario score or pass-rate regresses beyond the configured tolerance or safety violations increase.

## Judge policy

Deterministic checks run first. An optional LLM judge is allowed only after calibration and must never override safety or deterministic correctness gates.
