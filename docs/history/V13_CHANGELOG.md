## V13.0.0

- Added evidence-first adaptive algorithm portfolio for trend analysis.
- Added rolling-origin one-step-ahead validation for OLS vs Theil–Sen selection.
- Added lag-1 autocorrelation detection and deterministic moving-block bootstrap confidence intervals.
- Added persistent context-conditioned algorithm experience in SQLite.
- Added recency-weighted uncertainty-aware UCB scoring without random critical-path exploration.
- Added algorithm portfolio observability and `/algorithm-portfolio` CLI.
- Added adaptive algorithm learning to `diagnose_dataset` while explicitly separating operational utility from ground-truth accuracy.
- Fixed comprehensive relation analysis to preserve aligned complete-case rows.
- Added V13 benchmark and regression tests.
