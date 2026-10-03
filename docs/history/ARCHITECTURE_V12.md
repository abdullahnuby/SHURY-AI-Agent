# Personal Agent V12 — Evidence & Adaptive Analysis

V12 keeps the agent model-free and local. The main upgrade is from static descriptive analytics to an evidence engine that chooses robust algorithms from measurable data characteristics, records provenance, and monitors temporal drift.

## Algorithm layer
- Deterministic bootstrap confidence intervals with data-derived seeds.
- Theil–Sen robust trend estimation when outliers justify it; OLS otherwise.
- Robust MAD z-scores beside Tukey IQR, so anomaly findings have two independent signals.
- Mutual-information feature relations over deterministic quantile bins.
- Cliff's delta for distributional effect size support.
- Page–Hinkley online change detection.
- Beta-binomial posterior summaries for empirical tool reliability.

## Agent/data layer
- `diagnose_dataset` performs a complete evidence-oriented analysis.
- Every result carries a source fingerprint and explicit method names.
- Analysis is conservative: insufficient samples produce an explicit limitation rather than a fabricated test statistic.
- Runtime telemetry can be treated as analyzable data, enabling self-monitoring of failure/latency drift.

## Design principle
The agent should not choose an algorithm because it is fashionable. It chooses among a small audited portfolio using observable properties of the data, records why the method was chosen, and keeps the raw evidence reproducible.
