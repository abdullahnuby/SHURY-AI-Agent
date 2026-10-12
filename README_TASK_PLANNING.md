# SHURY V22.12 — Task Planning Core

## Purpose

V22.12 moves SHURY from “find a matching command” toward deterministic task reasoning without an LLM. The change preserves the existing execution, policy, verification, memory and tool contracts.

## Pipeline

```text
User text
  → semantic parse
  → TaskIR
  → method normalization/decomposition
  → capability grounding
  → state-aware local planning
  → cross-subtask dependency/dataflow
  → plan validation + certificate
  → runtime execution
  → observed state/evidence
```

## TaskIR

A `TaskIR` contains:

- high-level objective
- executable task nodes
- typed capability identity
- ordered dependencies
- success/evidence requirements
- constraints and explicit unresolved information
- planner-facing canonical goals

The raw user wording stays attached to each node so query-specific arguments are not lost during canonicalization.

## Deterministic methods

The current method library includes release-readiness auditing and research→evidence workflows. Method output is always converted back to ordinary task nodes and must still pass normal tool contracts and certification.

## State propagation

Each local subplan is solved against a virtual state that accumulates tool `produces`, `removes` and resource consumption from preceding planned nodes. This is planning-time simulation only; runtime applies state transitions again only after verified tool success.

## Procedural skill reuse

Verified multi-step skills are matched using ordered capability sequences before lifecycle evidence is considered. This allows a learned workflow to match a paraphrased goal even when the trigger words differ. The selected workflow is re-grounded against current TaskIR nodes and is never allowed to bypass live registry validation, certification, policy or approval.

## Current deliberate limitation

Arbitrary natural-language `if/else` control flow is still fail-closed. The next control-flow layer should introduce typed predicates, probe steps, branch guards and observation-driven replanning rather than executing an unverified branch.

## Verification

Focused Task Planning tests: 8 passed.

The repository-wide suite was executed by file and the modified/new planning tests passed. A single-process repository-wide run exceeded the execution environment timeout even though the affected suites were individually green; this should remain a release note until the harness is profiled end-to-end.
