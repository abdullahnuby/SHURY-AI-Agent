# SHURY Multi-Agent Executed Plan — Independent Audit

**Scope:** `SHURY-AI-Agent-excuted-plan.zip` compared against `SHURY-AI-Agent-main.zip` (the previous baseline archive). No source files were edited during this audit.

## Executive verdict

The implementation is a useful first vertical slice: the canonical `CognitiveKernel` is still the orchestrating entry point, the specialist contracts/registry/dispatcher exist, the memory projection correction is covered by a targeted test, and `run_cognitive` defaults to denial instead of implicit approval. However, **G1–G4 should not yet be marked fully accepted**. Several control fields are currently descriptive rather than enforced, and three execution-path defects were reproduced: workspace path escape through `DataAgent`, a DAG returning overall `success` while a node failed, and no actual timeout enforcement. A mismatched result task ID is also accepted as successful.

## Archive diff

- Baseline: 729 files.
- Executed archive: 741 files.
- Added: 12 files (agent package, registry tests, embedded audit report, and a workspace fixture artifact).
- Modified: 7 files (`app/brain/kernel.py`, `app/domain/task_graph.py`, `app/knowledge/memory.py`, `app/knowledge/memory_controller.py`, `app/runtime/cognitive_agent.py`, `tests/test_v23_cognitive_loop.py`, `tests/test_v5.py`).
- No files were deleted.
- `VERSION` remains `23.0.0-alpha1`.

## What passed

- `python -m compileall -q app tests`: passed.
- `python -m pytest tests/test_agent_registry.py -q`: **13 passed**.
- `python -m pytest tests/test_v23_cognitive_loop.py tests/test_v5.py -q`: **14 passed**.
- The memory revision regression (`revision == 2` and `belief_revision` history event) passes in the targeted suite.
- The approval-default regression passes: the adapter's default approval callback returns `False`.

## Confirmed findings

### P1 — DataAgent can read absolute paths outside the configured workspace

**Locations:** `app/agents/data_agent.py:40-80`; `app/knowledge/data_analysis.py` `_resolve_input_path()` / `load_rows()`; normal-action shortcut in `app/brain/kernel.py` `_run_action()`.

`DataAgent` passes its path directly to `profile_dataset()` / `answer_question()`. The data analysis resolver constrains relative paths, but resolves absolute paths and returns them without the `safe_workspace_path()` guard used by the existing `app/tools/data/analysis.py` adapter. The new specialist therefore skips an existing security boundary.

**Reproduction:** A temporary CSV created outside the workspace was passed to `CognitiveKernel.dispatch_specialist_task()` with capability `data_analysis`; the result was `success` and returned the two data rows. The same path through `_run_action()` succeeded when the approval callback returned `True`.

**Required fix:** Apply the same workspace-path policy used by the existing tool adapter before any specialist reads a file. Cover absolute paths, relative traversal, symlinks, `AGENT_WORKSPACE`, and the active-dataset reference. Ensure all public kernel dispatch/workflow entry points use the same enforcement.

### P1 — Specialist interception bypasses the canonical tool policy / verification path

**Location:** `app/brain/kernel.py` `_run_action()` branch for `profile_dataset` and `analyze_dataset`.

The branch dispatches directly to the specialist before the ordinary `tool.validate_args()`, `check_tool()`, and `verify_step()` flow. It calls `approve('data_analysis', args)` unconditionally, even when the registered tool policy would not require approval. This creates both sides of a regression:

- A routine low-risk data action may be denied when no approval callback is supplied, even if the central tool policy would allow it.
- If a callback approves, the direct path can skip central policy checks and still read a path outside the workspace.

**Required fix:** Preserve one policy gate. Resolve and validate the registered tool, call `check_tool()` with the actual tool and arguments, require explicit approval only when that policy requires it, enforce the workspace guard, then validate the specialist result against the same contract as the existing tool result. Do not represent a specialist response as verified merely because the call returned.

### P1 — A failed/partial DAG can be reported as successful

**Location:** `app/brain/kernel.py` `execute_specialist_graph()`.

The runner marks a node `failed` whenever its result status is not `success`, but its early-failure condition excludes the allowed `partial` status. If a `partial` node has a dependent node, that dependent remains pending; when no node is ready, the loop exits and returns overall `success` because at least one node ran.

**Reproduction:** A graph with node `a` returning `partial` and node `b` depending on `a` returned `status='success'` while graph state showed `a.status='failed'` and `b.status='pending'`.

**Required fix:** Only return overall success when every required node completed with status `success`; treat `partial` according to an explicit policy (default: non-success), set `node.output` / `node.error`, and include unresolved pending nodes in the returned failure report.

### P1 — Declared timeouts are not enforced

**Locations:** `app/agents/registry.py:70-111`; `app/agents/contracts.py` `AgentSpec.max_timeout_seconds` and `AgentTask.timeout_seconds`.

`dispatch()` invokes `agent.run(task)` synchronously and catches only a `TimeoutError` explicitly raised by the agent. Neither the task deadline nor the agent's maximum timeout is enforced by the registry.

**Reproduction:** A test agent configured with a 0.01-second maximum and task timeout slept for 0.1 seconds; dispatch still returned `success` after 0.1 seconds.

**Required fix:** Enforce deadlines with a mechanism that actually stops or isolates execution. A `Future.result(timeout=...)` alone is insufficient if the worker keeps running with access to resources. Since the first specialists are local and read-only, choose a bounded execution design and test non-cooperative slow agents.

### P1 — Registry accepts a result for a different task

**Locations:** `app/agents/registry.py:103-111`; `app/agents/contracts.py:94-104`.

The registry validates a result's shape but never checks `result.task_id == task.task_id`.

**Reproduction:** A specialist given task ID `requested-id` returned a success result with ID `different-id`; the registry accepted it as success.

**Required fix:** Reject task/result ID mismatches; validate evidence/error element types, status/output consistency, and any required evidence fields before accepting success.

### P1 — The verifier currently checks shape, not correctness

**Location:** `app/agents/verifier.py:56-90`.

The verifier sets `verified=True` when a profile contains `rows` / `columns` and analysis contains an `answer` or `method`. It does not recompute the claimed result, check the source fingerprint, validate provenance against the task, or prove that the answer is consistent with the profile/data. For example, an analysis payload containing `{"answer": null, "method": "anything"}` can pass the current check.

**Required fix:** Treat current behavior as schema validation, not verification. Implement independent deterministic checks for the first vertical slice (source fingerprint, rows/columns, expected calculation, and evidence lineage). Use distinct status labels for `schema_valid` and `verified` until those checks exist.

### P2 — Security/governance fields are currently advisory metadata

**Locations:** `app/agents/contracts.py`; `app/agents/base.py`; `app/agents/registry.py`.

`authority_scope`, `success_conditions`, `AgentSpec.allowed_tools`, `read_only`, and `resource_budget` are declared, but the dispatcher does not enforce their meaning. The timeout fields are similarly not enforced. The current design is a trusted in-process plugin interface, not a sandbox; a specialist implementation can still perform actions not prevented by code in the registry.

**Required fix:** Keep tool/policy authority central. Enforce or remove fields that are not yet meaningful; have each task declare the required success conditions and allowed capability. Document that `read_only=True` is not a sandbox guarantee. Do not claim capability isolation until the restrictions are enforced and tested.

### P2 — Specialist integration is only a partial vertical slice

The registry constructs Data, Development, Research, and Verifier specialists. However, the only normal planned-action interception in `_run_action()` is for `profile_dataset` / `analyze_dataset`. Development and Research are callable through direct dispatch but are not yet integrated into a general, typed capability-routing workflow from ordinary user requests. The explicit graph runner also maps a small hard-coded list of node tool names to capabilities.

**Required fix:** Finish one safe data-analysis workflow first; then add a typed, capability-based route for other domains without sentence-specific hardcoded rules.

### P2 — Test fixture leaked into the deliverable archive

`workspace/demo-app/pyproject.toml` is a new file in the executed archive. `tests/test_agent_registry.py::test_development_agent_inspects_project_without_writing` creates this fixed project under the repository workspace rather than under `tmp_path`. This dirties the workspace and makes the checked-in/archive contents depend on whether the test ran.

**Required fix:** Move the test fixture under `tmp_path`, remove the generated `workspace/demo-app/` artifact from the deliverable, and rerun the target test to ensure it leaves the workspace unchanged.

## Full-suite status and environment caveat

The executed archive collects **781 tests** (baseline collected 765). The full suite was not completed in this audit. The first failure on the executed archive was `tests/test_brain_arabic_nlp_bridge.py::test_brain_consumes_retrieval_native_arabic_memory_statements`, due to `ModuleNotFoundError: sentence_transformers` in the audit environment. I reproduced the same first failure on the baseline archive; it is an environment/dependency limitation rather than evidence that these code changes caused that failure. Do not claim the entire suite passes on the basis of the targeted tests alone.

## Gate assessment

| Gate | Assessment | Reason |
|---|---|---|
| G0 memory projection | Partial pass | Revision/history regression passes; `supersedes_id` projection was added. Confirm end-to-end provenance on more revision cases. |
| G0 approval default | Partial pass | Default-deny regression passes, but the specialist interception applies approval unconditionally and bypasses policy/verification. |
| G1 contracts + registry | Partial pass | Basic schema, duplicate capability, unknown capability, and exception tests pass; deadlines and task-result binding are not enforced. |
| G2 DataAgent | Not accepted | Functional tests pass, but absolute-path workspace escape is reproducible. |
| G3 kernel-owned graph | Not accepted | Partial node can cause false overall success; verifier is only schema-level. |
| G4 read-only Research/Development | Partial pass | Current methods are intended read-only and Development uses workspace guards, but the registry does not enforce read-only as a property and these specialists are not yet in a general user-to-agent routing path. |

## Recommended next patch sequence

1. **Security first:** unify workspace path checks and restore the canonical tool policy/approval/verification route for dataset actions.
2. **Correct status propagation:** make graph execution fail closed for partial/failed/pending nodes, validate task-result ID equality, and test dependency blockage.
3. **Enforce timeouts:** implement a genuine bounded execution boundary; test slow agents that do not raise `TimeoutError` themselves.
4. **Make verification honest:** separate schema validation from result correctness and add deterministic evidence/fingerprint checks.
5. **Fix test hygiene:** use `tmp_path` and remove generated workspace artifacts.
6. Rerun targeted tests, then run the complete suite in the project's supported Python environment with `sentence-transformers` and the configured Arabic retrieval model available. Preserve the constraint: no LLM runtime dependency or fallback; `omarelshehy/Arabic-Retrieval-v1.0` remains the required semantic retrieval model.

**Bottom line:** Keep this implementation as a promising prototype, but do not move to broader multi-agent routing or parallel execution until the P1 findings above are fixed and gated by regression tests.
