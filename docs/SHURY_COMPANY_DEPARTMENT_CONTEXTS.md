# SHURY Company — Department Execution Contexts (Company 6)

## Purpose

Company 6 gives every executable departmental task a bounded runtime context. The context is created after CEO assignment and before tool execution. It is task-scoped and ephemeral.

## Context contract

A `DepartmentExecutionContext` carries:

- company, task id, step id, department, specialist
- objective and the assigned tool/capability/skill
- explicit dependency step ids and Company handoff ids
- allowed input-reference names
- owned capabilities
- the current task's allowed tool (least privilege)
- memory policy (`task_local_only`)

Only structural metadata is persisted into `CognitiveState`. Raw dependency outputs remain in the execution engine and are made available only through explicit step dependencies.

## Isolation rule

A plan step that references `{{sN}}` must also declare `sN` in `depends_on`. The runtime rejects undeclared references before the tool is called. This prevents a later task from reaching back into an unrelated earlier task merely because its output happens to exist in the process.

## Handoffs

Cross-department dependencies are still represented by explicit `CompanyHandoff` records. The execution context exposes only the handoff ids relevant to the current task. Handoff contents are delivered through the existing dependency/output channel; they are not placed into global mutable departmental state.

## Memory

Company 6 does not change durable user-memory ownership. The existing memory subsystem remains authoritative for personal memory. Company working context is separate and ephemeral; a future organizational-memory phase will introduce persistent departmental/company memory with explicit scopes.

## Verification

The release includes isolation tests covering:

1. least-privilege tool scope
2. explicit dependency enforcement
3. declared dependency visibility
4. cross-department handoff visibility
5. context cleanup after execution
6. CognitiveState serialization

