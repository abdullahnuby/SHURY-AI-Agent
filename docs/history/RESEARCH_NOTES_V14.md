# V14 Research Notes — September 2026

## 1. Data Agents: Agentic Data Systems — 21 Sep 2026

The paper proposes semantic data organization, semantic operators, agentic pipeline orchestration, feedback-driven refinement, memory management and proactive adaptation. The implementation target for a model-free agent is the semantic organization/evidence layer: discover heterogeneous sources, expose explicit operators, retain provenance, and adapt only from measurable feedback.

Source: https://arxiv.org/abs/2609.24137

## 2. DataSpace — Aug 2026

DataSpace uses heterogeneous workspaces containing CSV, JSON, SQLite, Markdown, PDF and video, and evaluates agents with deterministic comparison of requested tabular results. Its results show that evidence integration and joins remain difficult even for modern agents. V14 therefore makes workspace discovery and join evidence first-class, deterministic capabilities.

Source: https://arxiv.org/abs/2608.03451
GitHub: https://github.com/HKUSTDial/DataSpace

## 3. DSAgentBench — Aug 2026

DSAgentBench evaluates full end-to-end data-science workflows in real computer environments with a deterministic evaluator, highlighting failures in tool orchestration and multi-step execution. V14 preserves explicit tool contracts and adds workspace-level orchestration rather than relying on one-file assumptions.

Source: https://arxiv.org/abs/2608.10366
GitHub: https://github.com/vis-nlp/DSAgentBench

## 4. Adaptive online kernel changepoint detection — Sep 18 2026

This work adapts the detector's memory and uses an MMD-style distribution statistic for streaming changes. V14 takes a deliberately simpler, auditable route: a robust recent-window Wasserstein signal and multivariate sliced Wasserstein comparison, while preserving the existing Page–Hinkley monitor.

Source: https://arxiv.org/abs/2609.22545

## 5. High-Dimensional Online Change Point Detection with Adaptive Thresholding — Sep 21 2026

The paper uses Sliced Wasserstein projections plus adaptive quantile thresholds for multivariate online CPD and provides interpretable change annotations. V14 adopts the projection/distribution-distance idea and adds column-level explanations, but does not claim the paper's theoretical guarantees because the implementation uses deterministic Gaussian hash projections rather than its Gamma-calibrated procedure.

Source: https://arxiv.org/abs/2609.24278
GitHub: https://github.com/jsve96/SWCPD_Code

## 6. Process-level evaluation — 2026

DataPRM reports that static process rewards can miss silent analytical errors. V14 keeps evidence certificates and explicit method provenance so successful execution is never treated as proof of statistical correctness.

Source: https://arxiv.org/abs/2604.24198
GitHub: https://github.com/zjunlp/DataMind

## 7. CIPHER / MLEvolve / EvoDS

These projects motivate separate candidate exploration from selection, executable search over algorithmic alternatives, and experience reuse. V13 already contains the adaptive algorithm portfolio; V14 extends the same evidence-first philosophy to workspace and drift operators.

Sources:
- https://arxiv.org/abs/2607.14386
- https://arxiv.org/abs/2606.06473
- https://arxiv.org/abs/2606.03841

## Deliberately not copied

- LLM-generated conclusions or code
- opaque embeddings/vector retrieval
- stochastic exploration in critical execution paths
- theoretical claims beyond what the local implementation actually guarantees
