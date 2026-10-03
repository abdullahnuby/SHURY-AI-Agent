# Personal Agent V13 — Adaptive Evidence & Online Algorithm Learning

V13 extends the V12 evidence engine without introducing an LLM, embeddings, network calls, or third-party Python packages.

## 1. Evidence-first algorithm selection

Trend analysis now evaluates OLS and Theil–Sen using rolling-origin one-step-ahead error. The selected method is therefore tied to observed predictive behavior on the current data rather than a fixed preference.

Historical experience is only a secondary signal. It is recency-weighted and uncertainty-aware, so learned history cannot override materially better current-data evidence.

## 2. Dependence-aware uncertainty

The engine estimates lag-1 autocorrelation. Weakly dependent data uses the existing deterministic IID bootstrap; materially dependent ordered data uses a deterministic moving-block bootstrap.

This avoids presenting ordinary IID intervals as if observations were independent when the row order contains a measurable serial signal.

## 3. Online algorithm experience

SQLite now stores `algorithm_observations(context, method, reward, verified, metadata, ts)`.

The adaptive learner uses a recency-weighted empirical utility estimate plus an exploration bound derived from effective sample size and observed reward variance. It is deterministic: no random exploration is used on the critical execution path.

The context key is built from measurable properties:

- sample-size bucket
- outlier-rate bucket
- missing-rate bucket
- numeric/categorical cardinality
- absolute lag-1 autocorrelation bucket

## 4. Learning safety

The recorded reward is explicitly **operational evidence utility**, not a claim of ground-truth statistical accuracy. A reward combines independent verification, evidence quality, and optional stability/efficiency signals.

Experience is advisory. All final outputs still pass deterministic verification, and cached plans are re-certified against the live world.

## 5. Runtime observability

`/analytics` now exposes the accumulated algorithm portfolio beside tool reliability, latency, horizon survival, EWMA, CUSUM, and change detection.

`/algorithm-portfolio` exposes the learned evidence history without mutating it.

## 6. Research-to-implementation mapping

- DataSpace / AgenticDataBench → deterministic, workflow-level evaluation and verifiable outputs.
- AutoData → treat data engineering / algorithm selection as an executable search problem.
- CIPHER → separate candidate exploration from selection; V13 keeps current-data evidence primary and uses experience as a controlled secondary signal.
- EvoDS → reusable experience and adaptation, implemented here as deterministic local memory rather than RL/LLM skill synthesis.
- Continuous agent evaluation research → nonstationarity-aware monitoring and uncertainty for runtime signals.
