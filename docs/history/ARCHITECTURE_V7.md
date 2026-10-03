# Personal Agent V7 Architecture

V7 is intentionally model-free. It borrows runtime ideas from current agent
systems while replacing model-generated decisions with deterministic contracts.

```text
                 USER GOAL
                    |
                    v
             Context Resolver
                    |
                    v
             Understanding Layer
                    |
                    v
        Capability / Operator Search
                    |
                    v
           State-Space Best First
                    |
                    v
             Plan + Dependencies
                    |
                    v
        Validation -> Policy -> Approval
                    |
                    v
                 Execute
                    |
          +---------+---------+
          |                   |
          v                   v
      Observation         Effect Ledger
          |
          v
   Postcondition Check
          |
          v
      World State
          |
     +----+----+
     |         |
   Goal      Mismatch
 complete       |
     |          v
     |       Replan
     |          |
     +----------+

Checkpoint is written at each control boundary. Resume loads the exact plan,
world state, outputs and next step; it never silently regenerates a new plan.
```

## V7 invariants

1. A tool call is not success until output verification passes.
2. A plan is executable only if its dependencies and tool schemas validate.
3. Side effects remain behind policy/approval boundaries.
4. Unknown conversational references do not get guessed.
5. Runtime state is durable and resumable.
6. Effect history is append-only and replayable without re-execution.
7. Replanning is bounded and evidence-based; no blind infinite retry loop.
8. Memory separates stored data from session state and records updates durably.
9. Planning cost is explicit and reliability is learned from observed outcomes.
10. User-visible completion is based on independent objective verification.

## Research-derived design choices

- Runtime-owned execution truth and explicit completion checks.
- Dependency-aware graphs and durable checkpoints/resume.
- Tool input/output guardrails at the runtime boundary.
- Memory as a persistent data-management subsystem with retrieval and maintenance.
- Evaluation focused on long-horizon stateful behavior, selective forgetting and
  recovery rather than only final text quality.
