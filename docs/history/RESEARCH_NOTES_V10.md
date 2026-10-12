# Research Notes — V10

## What was studied

- DeepPlanning (ACL 2026): explicit global constraints, active information
  acquisition and parallel tool use for long-horizon planning.
- Agent Planning Benchmark (APB, 2026): diagnostics for planning quality,
  tool noise robustness, calibrated refusal and inference-time refinement.
- Mem2ActBench (ACL 2026): persistent memory must be actively applied to
  tool parameters, not merely retrieved.
- π-Bench (2026): proactive personal assistants with hidden intents,
  inter-task dependencies and cross-session continuity.
- Simple Temporal Network / STNU work in 2026: temporal constraint propagation
  and controllability for uncertain durations.

## GitHub implementations studied

- `Mikivishy/AgentPlanningBenchmark`
- `Cantaloupe-M/Mem2ActBench`
- `Simplified-Reasoning/Pi-Bench`
- `tangle-network/agent-runtime`
- `veritiana/tenrec`
- `rohitg00/agentmemory`
- `shop-planner/shop3`
- `aiplan4eu/up-spiderplan`
- `openplan-labs/PythonPDDL`
- `axiom-llc/axiom-apex`
- `rmax-ai/durable-agent-runtime-lab`

## Why V10 stays LLM-free

The above systems cover many model-driven agents, but the user requirement is
specifically a personal agent that does not depend on an LLM. V10 therefore
imports the algorithmic ideas—explicit state, constrained planning, durable
execution, memory provenance, temporal reasoning, independent verification—
without importing model inference.
