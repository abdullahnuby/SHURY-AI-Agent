# Personal Agent V10 Architecture

V10 is a model-free deterministic agent runtime. It adds a constraint-first
planning layer on top of the V9 hierarchical runtime.

## Algorithms

V10 is intentionally a deterministic planner/runtime rather than a model wrapper.


1. **Hierarchical AND/OR search** — decomposes goals and recursively solves
   preconditions.
2. **Relaxed planning heuristic** — an h_add-like delete-relaxed lower bound
   for ordering and branch pruning.
3. **Landmark extraction** — conservative common-precondition landmarks.
4. **Risk-adjusted operator cost** — combines cost, risk and empirical
   reliability rather than treating all tools equally.
5. **Pareto-aware alternatives** — retains multiple feasible candidates for
   cost/duration/risk trade-offs.
6. **Simple Temporal Network (STN)** — verifies difference constraints and
   detects impossible schedules before execution.
7. **Partial-order scheduler** — critical-path execution with resource mutexes.
8. **Suffix repair** — after a verified prefix, re-plan only the unfinished
   portion against the live world state.
9. **Durable effect recovery** — a verified effect prevents duplicate side
   effects after process interruption.

## Deliberate boundaries

No LLM, embeddings, remote inference, hidden prompts, or stochastic planner
state are required for any of the above.

The runtime does not claim general human-level reasoning. Its guarantees are
only for the explicit world model, tool contracts, policies and search bounds
registered by the application.
