# V13 Research Notes — September 2026

## Highest-value signals reviewed

### DataSpace — August 2026
DataSpace frames data-agent quality as **verifiable analytics** over heterogeneous workspaces. Its evaluator performs deterministic, type-aware and order-aware comparison, reinforcing the V12/V13 decision that an analytical agent needs machine-checkable evidence rather than only a natural-language answer.

Source: https://arxiv.org/abs/2608.03451
GitHub: https://github.com/HKUSTDial/DataSpace

### AgenticDataBench — 2026
AgenticDataBench evaluates realistic end-to-end data-science workflows and provides fine-grained skill labels, showing that skill-level failure analysis is more informative than one aggregate score.

Source: https://arxiv.org/abs/2607.01647
GitHub: https://github.com/AgenticDataBench/AgenticDataBench

### AutoData — September 17, 2026
AutoData searches directly over executable data-selection algorithms and uses validation feedback to refine candidate rules. The transferable idea for this project is that data handling / algorithm choice can itself be treated as a search problem over executable methods, not merely static configuration.

Source: https://arxiv.org/abs/2609.19754
GitHub: https://github.com/WecoAI/AutoData

### CIPHER — July 2026
CIPHER separates exploration from selection in data-science agents. V13 mirrors the separation: multiple algorithm candidates are evaluated on the current dataset, then a deterministic selector chooses among them; historical experience remains secondary.

Source: https://arxiv.org/abs/2607.14386

### EvoDS — June 2026
EvoDS treats reusable skills and context management as learned components of long-horizon agents. V13 adopts the experience-reuse principle while deliberately keeping the project model-free and deterministic.

Source: https://arxiv.org/abs/2606.03841
GitHub: https://github.com/usail-hkust/EvoDS

### Continuous agent uncertainty — May 2026
Recent work adapts conformal methods to continuous agent evaluation and emphasizes widening uncertainty after distribution changes. V13 does not claim conformal guarantees; instead it adopts the safer operational principle of treating agent quality as a time-varying signal and explicitly detecting nonstationarity.

Source: https://arxiv.org/abs/2605.19779

## Algorithm decisions

### Adopted
- rolling-origin validation for trend-method choice
- moving-block bootstrap for ordered/dependent observations
- recency-weighted empirical-Bernstein-style UCB for deterministic experience ranking
- explicit context-conditioned algorithm memory
- independent evidence verification before recording useful experience

### Deliberately not adopted
- LLM-generated code or critiques
- stochastic online learning in the critical path
- embeddings/vector databases
- external cloud services
- claims of statistical correctness based solely on runtime success

## Design rule

The agent may learn **which method has historically been operationally useful in a measured context**, but it may never use historical memory as a substitute for current-data evidence or verification.
