# V7 Research Notes — September 2026

This project remains **No LLM / No external model / No embeddings**. The research was
used for runtime architecture, not for model inference.

## Research / benchmarks reviewed

1. **Agent Memory: Characterization and System Implications of Stateful Long-Horizon Workloads**
   arXiv:2606.06448 (June 2026). Key lesson: treat memory as a data-management subsystem
   with distinct storage, retrieval, maintenance and workload costs.

2. **Are We Ready For An Agent-Native Memory System?**
   arXiv:2606.24775 (June 2026). Key lesson: persistent memory needs explicit representation,
   retrieval/routing, update correctness and lifecycle maintenance; local maintenance can be
   preferable to global reorganization.

3. **Agent JIT Compilation for Latency-Optimizing Web Agent Planning and Scheduling**
   ICML 2026. Key lesson: explicit planning, alternative candidate plans, cost-based selection,
   scheduling and invariant-enforcing pre/post conditions are useful runtime boundaries.

4. **Towards a science of scaling agent systems: When and why agent systems work**
   Google Research, January 28 2026. Key lesson: parallel/multi-agent execution is not universally
   beneficial; coordination should match task structure, especially parallelizable vs sequential work.

5. **Long-Horizon-Terminal-Bench** and 2026 memory benchmark work. Key lesson: evaluation should
   measure partial progress, long-horizon recovery and stateful memory behavior rather than only final text.

## GitHub runtimes / systems reviewed

- `tangle-network/agent-runtime`: exact run identity, durable resume, truthful accounting,
  independent completion checks, graph execution and observed effects.
- `clearideas/agent-runtime`: versioned manifests, dependency-aware scheduling, durable checkpoints,
  suspension/resume, cancellation, SQLite stores and execution boundaries.
- `openai/openai-agents-python`: explicit sessions, guardrails, tool boundaries and tracing.
- `langchain-ai/docs`: short-term checkpoints versus long-term stores; persistent checkpointers for
  interruption/resume and fault tolerance.
- 2026 GitHub memory benchmarks such as `AlekseiMarchenko/agent-memory-benchmark` and
  `cmenguy/agent-memory-bench`: deterministic tests around recall, temporal/conflict behavior,
  selective forgetting and cross-session persistence.

## What V7 adopts

- machine-readable capability contracts
- bounded best-first plan search
- explicit cost/reliability/risk inputs
- state transition evidence
- durable checkpoints and exact-plan resume
- append-only effect ledger
- independent objective verification
- bounded evidence-based replanning
- persistent memory maintenance features including selective forgetting
- deterministic architecture-level evaluation

## What V7 intentionally does not adopt

- LLM inference
- prompt-based planning
- embeddings or vector databases
- hidden autonomous retries
- model-as-judge evaluation
- multi-agent decomposition without a task-structure reason

The result is a small local deterministic runtime that can later host richer
natural-language models as an optional adapter without making them a runtime dependency.
