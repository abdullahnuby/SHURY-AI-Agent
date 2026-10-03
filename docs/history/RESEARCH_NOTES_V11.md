# V11 Research Notes

## Research themes reviewed (September 29, 2026)

- DataClaw: process-oriented evaluation for exploratory real-world data analysis; intermediate milestones matter, not only final answers.
- DataSpace: heterogeneous workspace analytics, complete tabular outputs, provenance and deterministic evaluation.
- DataMind: data-analysis skills, process supervision and long-horizon data work.
- EvoDS: reusable skills + long-horizon context management. Only the skill/reuse idea is translated here; no LLM/RL is used.
- Mem2ActBench: memory should be evaluated by downstream task usage, not recall alone.
- TraceCore / current runtimes: reproducible execution, hard budgets, binary/evidence-grounded validation, replay.
- Causal Discovery in the Era of Agents: agents may assist the analytical workflow, but causal conclusions should remain grounded in formal algorithms, assumptions, diagnostics and expert input.

## What V11 implements

1. A standard-library-only analytical engine with CSV, JSON and SQLite readers.
2. Deterministic schema inference and data-quality scoring.
3. Robust statistics: quartiles, IQR, MAD, Tukey outliers, Pearson and Spearman correlation, linear trend and R².
4. Evidence records with file fingerprint and method name.
5. Dataset comparison for schema drift and numeric distribution change.
6. A capability-first data analysis tool surface for the Agent.
7. Runtime self-analysis: p50/p95 latency, tool failure rate, retry counts, horizon survival and deterministic degradation alerts.

## Deliberate non-adoptions

- No LLM-generated Python execution.
- No embeddings/vector database.
- No causal edge generation. Causal claims require explicit statistical assumptions and formal causal tooling beyond this V11 scope.
- No autonomous skill synthesis from arbitrary code. Reuse remains contract-based and verified.
