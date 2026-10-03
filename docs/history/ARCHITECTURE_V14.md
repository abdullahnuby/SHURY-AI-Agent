# Personal Agent V14 — Heterogeneous Evidence & Multivariate Drift

V14 keeps the model-free/deterministic constraint and extends V13 in two directions: workspace reasoning and distribution-level monitoring.

## 1. Heterogeneous workspace evidence

A workspace is recursively catalogued into table sources (CSV/JSON/SQLite) and text evidence (Markdown/plain text). Every source receives a content fingerprint and machine-readable metadata.

For table pairs, the engine normalizes likely semantic key names (for example customer_id, id, معرّف) and then measures observed value overlap. Candidate joins are ranked from evidence, with a deterministic exact-key join executor and left-match-rate measurement.

The system does not infer a join merely from column-name similarity: a usable candidate also needs observed value overlap.

## 2. Multivariate distribution drift

V14 implements a lightweight deterministic approximation of the current research direction using distributional distances in projected space. Numeric feature matrices are standardized against the baseline distribution, projected along hash-derived Gaussian directions, and compared using empirical 1-Wasserstein distance.

This yields:

- global sliced-Wasserstein distance
- projection variability
- per-column standardized Wasserstein distance
- global and local drift alerts

The projection generator deliberately uses cryptographic hashing rather than the small modulo-based V12 PRNG, because low-modulus sampling can repeat directions and hide multivariate shifts.

## 3. Ordered-stream monitoring

For one-dimensional ordered data, V14 adds an adaptive recent-window Wasserstein signal. The reference is robustly centered/scaled using median and MAD, then compared with a recent suffix. This complements the existing Page–Hinkley detector rather than replacing it.

## 4. Agent integration

Two executable capabilities are available:

- `analyze_workspace(path)` — catalog + join-evidence graph
- `compare_sources_drift(left,right)` — multivariate numeric distribution comparison

Workspace analyses are also written to durable local event memory for later audit.

## 5. Safety/correctness boundaries

Current-data evidence remains primary. Workspace discovery never claims an inferred semantic relationship is true merely because names look similar. Every reported join is grounded in observed value overlap, and drift reports identify the mathematical method used.
