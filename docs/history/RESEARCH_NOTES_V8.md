# V8 Research Notes — September 29, 2026

This review was performed before the V8 implementation. The goal was not to
copy model-driven agents into a no-LLM system, but to identify runtime principles
that remain useful when all decisions must be deterministic.

## Research / benchmarks

### DeepPlanning (ACL 2026)
https://aclanthology.org/2026.acl-long.335/

Focus: long-horizon planning under verifiable constraints, active information
gathering, local constraints and global optimization. The paper reports that even
frontier LLM agents struggle with these tasks and highlights explicit reasoning
patterns and parallel tool use.

Adopted in V8:
- explicit max-cost / max-duration constraints
- dependency graph execution
- deterministic parallel fan-out for safe independent tasks
- benchmark-style verification rather than text-only completion

### Beyond pass@1: A Reliability Science Framework (2026)
https://arxiv.org/abs/2603.29231

Focus: capability versus repeated long-horizon reliability, with Reliability
Decay Curve, Variance Amplification Factor, Graceful Degradation Score and
Meltdown Onset Point.

Adopted in V8:
- per-tool empirical reliability
- run-level reliability
- horizon-survival curve
- keep reliability separate from simple single-run capability

We do not claim V8 reproduces the paper's full statistical methodology; our
metrics are a smaller deterministic runtime diagnostic.

### InfiAgent (ACL 2026)
https://aclanthology.org/2026.findings-acl.1787/
https://github.com/polyuiislab/infiAgent

Focus: bounded reasoning context by externalizing persistent state, plus resumable
long-horizon execution and crash-safe persistence.

Adopted in V8:
- state externalization into SQLite checkpoints
- durable effect ledger
- verified-effect recovery on resume
- bounded recent session state

### π-BENCH (2026)
https://github.com/Simplified-Reasoning/Pi-Bench
https://arxiv.org/abs/2605.14678

Focus: proactive personal-assistant behavior across persistent multi-session
workflows, measuring Proactivity and Completeness.

Adopted in V8:
- persistent workspace/run history
- dependency-aware multi-session state
- a deterministic separation between incomplete/clarify and execute
- architecture-level completeness checks

Not adopted literally:
- hidden-intent inference that requires an LLM or benchmark-specific judge

### Agent Zero Memory (2026)
https://arxiv.org/abs/2608.29606

Focus: provenance-aware long-term memory with separate episodic, entity-linked
and curated semantic stores, plus source routing and abstention.

Adopted in V8 at a deterministic scale:
- semantic facts
- episodic run/event history
- procedural plan experience
- provenance fields on facts/notes
- conservative recall and abstention when context is absent

Not adopted:
- embedding-based semantic retrieval and agentic multi-search loops

## GitHub systems

### rohitg00/agentmemory
https://github.com/rohitg00/agentmemory

Observed current repository state on 2026-09-29: large persistent-memory runtime,
local keyless BM25 path, lifecycle, confidence, graph/structured recall and a
strong emphasis on reproducible retrieval evaluation.

Adopted in V8:
- local lexical ranking
- importance/confidence/lifecycle concepts
- benchmark-first memory evaluation

Not adopted:
- external iii engine
- embeddings as a runtime dependency

### polyuiislab/infiAgent
https://github.com/polyuiislab/infiAgent

Observed current repository state on 2026-09-29: configuration-defined agent
systems, file-centric task state, crash-safe persistence, atomic writes and
experience-store concurrency controls.

Adopted:
- externalized state
- resume/recovery discipline
- persistent experience store

### tangle-network/agent-runtime
https://github.com/tangle-network/agent-runtime

Observed current repository state on 2026-09-29: exact execution, durable run
control, truthful accounting, independent completion checks, supervision and
replay/conformance boundaries.

Adopted:
- execution truth separated from claims
- independent completion verification
- append-only run/effect accounting
- replay without re-execution

### JH427/Horizon-Pi-Bench
https://github.com/JH427/Horizon-Pi-Bench

Observed benchmark design on 2026-09-29: long-horizon, multi-session personal-assistant
workflows with persistent workspaces, underspecified requirements and explicit
proactivity/completeness metrics.

Adopted:
- persistent workspace state
- multi-session benchmark cases
- conservative handling of missing information

## Design decisions that were intentionally rejected

- No LLM router.
- No prompt-based planner.
- No embedding API dependency.
- No vector database dependency.
- No unconstrained autonomous loops.
- No “memory” that can silently override current verified state.
- No claim that passing local tests equals general intelligence.

## Implementation target

V8 is therefore a **deterministic agent runtime**: a system that can represent a
goal, search over explicit operators and state transitions, execute with policy,
verify results, persist durable evidence, recover after interruption and learn
safe procedural priors from verified experience.
