# SHURY Company 7 Release

## Scope

Company 7 adds deterministic coordination and scheduling on top of the Company 6 organization core.
The executive DAG remains authoritative; scheduling chooses execution batches only among tasks
whose dependencies are already satisfied.

## Runtime contract

- `Tool.parallel_safe=True` is required for concurrent execution.
- Approval-gated actions are never dispatched in a parallel batch.
- Exclusive resources are never shared by a parallel batch.
- Non-autonomous Company authority is not parallelized.
- Each parallel task receives an isolated transient `CognitiveState` view; raw peer outputs remain
  inaccessible unless declared as dependencies.
- Batch results are committed back in deterministic task order.
- If a parallel task fails, successful peer results are retained; downstream work is reconsidered
  only after the batch is committed.

## Verification

Company scheduler and execution regression: 41 passed.
The focused V23/canonical suite passes after explicit ownership declarations for
`question_answering` and `agentic_rag`. The pre-existing memory revision test remains outside this
phase and is not changed here.
