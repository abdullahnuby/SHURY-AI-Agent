# Personal Agent V8 Architecture

V8 is intentionally **model-free**. It implements a deterministic agent runtime
with explicit state, operators, planning, verification and memory.

```text
                          +------------------+
                          |      USER        |
                          +---------+--------+
                                    |
                                    v
                          +------------------+
                          | Context Resolver |
                          | Understanding    |
                          +---------+--------+
                                    |
                                    v
                          +------------------+
                          | Goal Model       |
                          | Clauses          |
                          | Constraints      |
                          +---------+--------+
                                    |
                                    v
                     +--------------+--------------+
                     |      Search Planner        |
                     | best-first state search    |
                     | precondition support       |
                     | cost/risk/reliability      |
                     +--------------+--------------+
                                    |
                                    v
                          +------------------+
                          | Plan Validator   |
                          +---------+--------+
                                    |
                                    v
                          +------------------+
                          | Policy / Approval|
                          +---------+--------+
                                    |
                                    v
                     +--------------+--------------+
                     | Dependency Scheduler        |
                     | serial where required       |
                     | fan-out when independent   |
                     +--------------+--------------+
                                    |
                              +-----+-----+
                              |           |
                              v           v
                         Execute       Observe
                              |           |
                              +-----+-----+
                                    |
                                    v
                          +------------------+
                          | Postcondition    |
                          | Verification     |
                          +---------+--------+
                                    |
                                    v
                          +------------------+
                          | World State      |
                          | facts/resources  |
                          | elapsed/history  |
                          +---------+--------+
                                    |
               +--------------------+-------------------+
               |                    |                   |
               v                    v                   v
        Effect Ledger          Checkpoint         Experience Cache
               |                    |                   |
               +--------------------+-------------------+
                                    |
                                    v
                          Replan / Recovery / Finish
```

## State-space planning

The planner expands a node containing:

- completed goal clauses
- world capability facts
- resources
- elapsed duration
- accumulated real search cost
- selected operator sequence

The priority is based on:

```text
path_cost
+ reliability penalty
+ risk penalty
+ duration penalty
+ support penalty
+ remaining-goal heuristic
```

The heuristic is intentionally not claimed to be mathematically admissible; it
is a deterministic search ordering that balances practical execution cost and
risk.

When a matched operator is blocked by a missing precondition, V8 searches the
operator registry for a deterministic producer of that fact and inserts it when
valid. This is bounded to prevent combinatorial explosion.

## Partial-order execution

The planner emits explicit `depends_on` edges. The runtime calculates ready
steps from the graph rather than assuming list position is the dependency model.
Independent, read-only/side-effect-safe steps marked `parallel_safe` may execute
concurrently; results are committed back into the world in deterministic plan
order.

## Durable recovery

The critical ordering is:

```text
execute tool
  ↓
verify output
  ↓
write effect ledger
  ↓
apply world transition
  ↓
write checkpoint
```

If the process dies after the ledger write but before the checkpoint, resume
examines the latest verified effect for each pending step. A recorded verified
effect is treated as completed evidence and is not executed again.

SQLite uses WAL + busy timeout. Checkpoints contain a SHA-256 integrity hash over
plan, outputs, world, next index and status.

## Memory architecture

V8 separates memory into three deterministic lanes inspired by current agent
memory research:

- **semantic**: active facts and user knowledge
- **episodic**: prior runs/events
- **procedural**: verified successful plans and their measured cost/duration

Notes use local BM25-like retrieval plus exact phrase, freshness and importance
signals. There is no embedding service in the runtime.

## Learning without an LLM

Learning is deliberately conservative:

1. only verified successful executions update the experience cache;
2. repeated success updates empirical averages;
3. failed runs increment failure counts;
4. a cached plan can be reused only for the same normalized goal key;
5. the cached plan still goes through schema validation, policy and runtime verification.

## Evaluation

V8 evaluates long-horizon behavior using architecture-level measurements:

- verified tool reliability
- run completion reliability
- horizon survival by step depth
- recovery without duplicate execution
- checkpoint integrity
- memory retrieval and forgetting
- cost/duration constraint satisfaction
- deterministic parallel fan-out

No LLM-as-judge is used.
