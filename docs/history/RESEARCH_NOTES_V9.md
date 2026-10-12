# V9 Research Notes — 2026-09-29

This note records the most relevant current work reviewed before the V9 implementation.
The project requirement is strict: no LLM, no embedding model and no remote service.
Therefore only architectural ideas that remain meaningful in a deterministic runtime were adopted.

## Research

### Agent Planning Benchmark (APB) — June 2026
https://arxiv.org/abs/2606.04874

APB separates planning correctness from downstream execution and explicitly tests broken
tools, extraneous tools, unsolvable tasks, feedback-conditioned planning and robustness.

**Applied to V9:** planning diagnostics, explicit failure/unsat reporting, alternative
operator branches, and tests that separate planning failures from execution failures.

### STRUCTUREDAGENT — March 2026
https://arxiv.org/abs/2603.05294

Introduces hierarchical online planning with dynamic AND/OR trees and structured memory.

**Applied to V9:** deterministic AND/OR planning: AND for required subgoals/preconditions
and OR for alternative operators. We intentionally do not copy the LLM-based semantic planner.

### HIPIF — June 2026
https://arxiv.org/abs/2606.10507

Uses explicit subgoals and information folding to control long-horizon interference.

**Applied to V9:** goal phases and compact temporal projections so the runtime can retain
structured state without replaying raw history as its only context.

### Agent Memory: Characterization and System Implications — June 2026
https://arxiv.org/abs/2606.06448

Characterizes memory systems across construction, retrieval and update paths and emphasizes
freshness, capability floors, amortization and lifecycle tradeoffs.

**Applied to V9:** memory remains an explicit subsystem; retrieval is lexical and bounded;
procedure/episode/semantic stores stay separated; routine discovery is conservative.

### TiMem — ACL 2026 Findings
https://arxiv.org/abs/2601.02845
https://github.com/TiMEM-AI/timem

Uses a five-level temporal memory tree and temporal ordering for long-horizon conversations.

**Applied to V9:** a model-free five-level temporal projection with provenance. We do not claim
semantic consolidation because that would require a semantic model; higher levels are temporal
indexes and lexical topic hints only.

## GitHub systems reviewed

### Tangle agent-runtime
https://github.com/tangle-network/agent-runtime

Observed themes: exact execution, durable run control, independent completion, graph execution,
replay and truthful accounting.

**Applied:** durable checkpoints, effect ledger, independent verification, plan graphs and replay.

### Clear Ideas Agent Runtime
https://github.com/clearideas/agent-runtime

Observed themes: declarative manifests, deterministic graph scheduling, dependency-safe fan-out,
approvals, checkpoints and fresh-process resume.

**Applied:** explicit dependency graph, deterministic parallel scheduling, tool contracts and resume.

### InfiAgent
https://github.com/polyuiislab/infiAgent

Observed themes: externalized state, crash-safe persistence, atomic recovery and experience store.

**Applied:** durable runtime state and verified-effect recovery; no external model provider copied.

### agentmemory
https://github.com/rohitg00/agentmemory

Observed themes: persistent memory, BM25 in keyless mode, lifecycle/confidence, evaluation and
structured recall.

**Applied:** local lexical retrieval, lifecycle/provenance, deterministic memory evaluation.

### AURA
https://github.com/Adaptive-Intelligence-Research-Lab/AURA

Observed themes: event-driven capability execution, state manager, governance gate and evidence-driven
validation.

**Applied:** capability contracts, policy gate, state transitions/effects and evidence-based completion.

### π-Bench
https://github.com/Simplified-Reasoning/Pi-Bench
https://arxiv.org/abs/2605.14678

Observed themes: proactive personal-assistant behavior, persistent workspaces, multi-session workflows,
underspecified requirements, Proactivity and Completeness metrics.

**Applied:** multi-session durable state and conservative routine discovery. We do not attempt hidden-intent
inference because that would violate the no-LLM requirement.

## Deliberate non-adoptions

- No LLM router or semantic judge.
- No vector database or embedding dependency.
- No autonomous scheduling from behavioral frequency alone.
- No uncontrolled infinite loops.
- No claim that local benchmark scores imply general intelligence.
