# Personal Agent V9 Architecture

V9 extends the model-free runtime into a deterministic hierarchical planner and
temporal memory system. The design borrows runtime principles from current 2026
agent systems but removes model/embedding dependencies.

```text
USER
  │
  ▼
Context + Understanding
  │
  ▼
Goal Compiler
  │   └─ constraints / AND groups / THEN phases
  ▼
Hierarchical AND/OR Search
  │   ├─ AND: required clauses / preconditions
  │   ├─ OR: operator alternatives
  │   ├─ recursive prerequisite closure
  │   └─ bounded branch-and-bound
  ▼
Plan Frontier (N-best valid candidates)
  │
  ▼
Plan Validation + Policy
  │
  ▼
Temporal / Resource Scheduler
  │   ├─ dependency critical path
  │   ├─ parallel-safe fan-out
  │   └─ exclusive-resource mutex
  ▼
Execution + Verification
  │
  ├──────────────┐
  ▼              ▼
World State     Effect Ledger
  │              │
  └──────┬───────┘
         ▼
Durable Checkpoint / Recovery
         │
         ▼
Replan / Experience Learning
         │
         ├─ verified plan cache
         ├─ routine candidates
         └─ temporal memory hierarchy
```

## Hierarchical planning

A goal with clauses joined by `and` is treated as an AND node. Each natural-language
clause is an OR node over all matching registered operators. If an operator requires
a missing fact, the planner recursively searches for producer operators for that fact.
This continues until the prerequisite closure is satisfied or the branch is proven
infeasible. Search is bounded by node count, candidate width, cost and step limits.

The planner retains a small frontier of valid alternatives. The selected plan is
minimized by real operator cost, then critical-path makespan, then step count. Risk and
empirical reliability influence search cost but are not confused with monetary cost.

## Temporal planning

Plan duration is a critical path, not a sum, when independent steps can be parallelized.
Tools can additionally declare `exclusive_resources`; the scheduler serializes steps
sharing those resources. The executor applies the same mutex before creating a parallel
batch, so the schedule and runtime share one safety rule.

Explicit `max_duration`, `max_cost` and `max_steps` constraints are hard limits.

## Recovery

The durable sequence remains:

```text
execute → verify → effect ledger → state transition → checkpoint
```

On resume, a verified effect already present in the ledger is recovered rather than
executed again, preventing duplicate non-idempotent side effects across a crash boundary.

## Memory

V9 keeps three operational stores and adds a temporal projection:

- Semantic: active facts with revision/history/provenance.
- Episodic: completed and failed runs/events.
- Procedural: verified plans and measured outcomes.
- Temporal projection: five compact time levels with source provenance.

The temporal projection is deliberately lexical/temporal rather than semantic. No hidden
LLM summarizer is used. Higher levels are compact indexes, while raw evidence remains
recoverable at level 1.

## Conservative learning

Repeated completed goals produce `candidate_routine` records. The runtime never silently
schedules or executes a discovered routine. Automatic action remains behind explicit
user intent, policy and verification.

## Evaluation

V9 adds diagnostic planning tests for:

- alternative operator selection
- recursive prerequisite closure
- AND-order freedom
- unsatisfiable goal reporting
- critical-path scheduling
- exclusive-resource serialization
- temporal memory projection
- repeated-goal routine discovery
- pipeline compatibility

The complete suite is currently 65 tests; the V9 capability benchmark passes 5/5.
