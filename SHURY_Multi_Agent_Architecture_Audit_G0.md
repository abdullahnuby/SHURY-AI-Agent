# SHURY Multi-Agent Architecture Audit — G0

**Source reviewed:** `SHURY-AI-Agent-main.zip` provided in this conversation  
**Declared version:** `23.0.0-alpha1`  
**Review boundary:** static source review, architecture/path tracing, test collection, compilation, and selected automated tests. No source files were changed.

## Executive conclusion

Do not rebuild SHURY or create a second Brain. Keep `CognitiveKernel` as SHURY's central manager and add a small, local, hybrid agent layer around existing capabilities. Agents should be task-specialist modules with strict capability scopes; the central runtime remains the only authority for policy, approvals, side effects, verification, and final response.

The biggest prerequisite is not creating agents yet: establish one canonical entry path for the features being developed and make the current acceptance baseline explicit. The code currently exposes more than one natural-language execution path, and the canonical Brain does not consume the legacy task compiler used by `run_agent`.

## Snapshot and verification

- 729 files extracted from the ZIP; 115 top-level Python test modules were present, plus fixture/report/data files.
- `VERSION` is `23.0.0-alpha1`.
- `python -m compileall -q app tests`: passed.
- `python -m pytest --collect-only -q`: 765 tests collected.
- Selected gates `tests/test_architecture_boundaries.py`, `tests/test_phase20_security.py`, `tests/test_task_planning_core.py`: **34 passed**.
- A broader V23/chat subset: **25 passed, 1 failed**. Failure: `test_belief_revision_preserves_history_event`; `_load_beliefs()` in `app/brain/kernel.py` projects `revision=1` for every memory item, losing the observed revision.
- Full-suite attempt could not be completed in this environment. First failure: `test_brain_consumes_retrieval_native_arabic_memory_statements`, because this execution environment does not have `sentence_transformers` installed while the test explicitly sets `SHURY_NLP_MODE=required`. `requirements.txt` does declare `sentence-transformers>=5.0`; this result is an environment blocker, not proof the target Windows environment is missing it.
- `tests/test_v8.py::test_parallel_ready_steps_are_executed_concurrently`: passed when run independently. Historical documentation that mentions a concurrency failure should not replace a current measured baseline.
- A fresh read of the current GitHub files agreed with this ZIP's `VERSION` and README: this snapshot is V23 alpha1 and has no `app/organization/` package. Any previously observed V27/organization file view is not part of this current snapshot and should not drive changes to it.

## Architecture actually present

### Cognitive core and tool execution

- `app/brain/kernel.py`: `CognitiveKernel`, perception, memory evidence, goal formation, planning, action execution, verification, re-planning, and learning.
- `app/brain/models.py`: typed `GoalSpec`, `CognitiveState`, `Capability`, `CandidateAction`, `PlannedAction`, `ActionSpec`, evidence and transition structures.
- `app/brain/capabilities.py`: exposes registered tools as capabilities and chooses candidates for known operations.
- `app/brain/methods.py`: deterministic procedural methods. Most registered methods currently create one action; the compound calculation-and-remember method creates a two-step plan.
- `app/brain/planner.py`: ranks method plans with cost and verified-experience signals; may use existing model-based planning/exploration mechanisms.
- `app/runtime/registry.py`: a **tool** registry (`Tool` contracts), not an agent registry. It already contains risk, approval, precondition/effect, idempotency, `parallel_safe`, and resource declarations.
- `app/runtime/policy.py` and `app/runtime/verify.py`: existing central policy and verification boundaries to retain.
- `app/knowledge/memory.py`, `app/knowledge/memory_controller.py`, `app/learning/store.py`: existing memory/experience infrastructure. Do not add one independent persistent memory database per agent.

### Existing task decomposition and concurrency are on a different route

- `app/intelligence/task_compiler.py`, `app/domain/task_ir.py`, `app/domain/task_graph.py`, `app/planning/task_planner.py`, and related planning modules implement pieces of typed multi-step task planning.
- In the current snapshot, `compile_task_ir()` is used from `app/runtime/agent.py`; it is not wired into `CognitiveKernel._plan_state()`.
- `app/runtime/agent.py` has an existing concurrent ready-step path using `ThreadPoolExecutor` for tools marked `parallel_safe` and not requiring approval.
- `app/planning/scheduler.py` computes a schedule/critical path; it does not itself execute tasks.
- `app/domain/task_graph.py::TaskGraph.validate()` checks duplicate IDs, missing dependencies, and self-dependencies, but does not currently reject general dependency cycles.
- `CognitiveKernel._execute_result()` currently consumes its pending plan serially. Multi-agent parallelism therefore should not be added by simply flipping a concurrency switch in the Brain loop.

### Runtime paths are not unified across interfaces

- Web `/api/chat` normally calls `run_brain()` → `CognitiveKernel.act()`.
- Web can choose `run_cognitive()` with `SHURY_ENABLE_COGNITIVE_UI=1`, or the legacy `run_agent()` with `SHURY_USE_LEGACY_RUNTIME=1`.
- The CLI's `/agent` and ordinary text paths currently call `run_agent()`.
- `run_cognitive()` separately parses through `SemanticInterpreter` and then calls `CognitiveKernel.act_structured()`; `run_brain()` uses `CognitiveKernel.act()` and its own perception/semantic path.
- These paths are all useful compatibility surfaces today, but a new multi-agent manager must not be wired inconsistently into only one of them by accident.

## Findings to resolve before multi-agent work

### G0-A — Make the execution baseline reproducible

Run the model-backed tests in the actual Windows `.venv` with `sentence-transformers` and the required `omarelshehy/Arabic-Retrieval-v1.0` weights available. Keep `SHURY_NLP_MODE=required` for this gate; do not count a lexical/off-mode run as proof of the model-backed path. Save the command and result so later phases have a meaningful baseline.

### G0-B — Fix and test the memory projection revision bug

`app/brain/kernel.py::_load_beliefs()` hardcodes `revision=1` and `supersedes=""` instead of preserving revision metadata from canonical Memory evidence. This causes `test_belief_revision_preserves_history_event` to fail even though the newest value is visible. Since agents will share canonical evidence, the provenance/revision projection must be reliable before multi-agent task handoffs depend on it.

### G0-C — Fail closed for approval defaults

`app/runtime/cognitive_agent.py::run_cognitive()` defaults `approve=lambda t, a: True`, while the canonical `CognitiveKernel._execute_result()` correctly defaults to deny. Web passes its approval broker explicitly, but direct callers that omit `approve` can receive different behavior. The default should be deny, with an explicit approval callback required for side effects; add a regression test at the wrapper/API boundary.

### G0-D — Choose the canonical manager integration point

For the new system, `CognitiveKernel` should remain the manager and the source of goals, grounded state, decision records, memory/learning integration, and final responses. The new agent dispatcher should be a subordinate service, not a second planner/brain. After the first vertical slice works, route interfaces deliberately and test them; do not silently rewrite every legacy path in the first change.

### G0-E — Strengthen task-DAG validation before agent scheduling

Any delegation graph needs duplicate-ID checks, missing-dependency checks, cycle detection, bounded depth/step count, timeout handling, cancellation, and deterministic result merging. Existing graph structures can inform this, but `TaskGraph.validate()` alone is insufficient for safe delegation.

## Recommended hybrid design

1. **SHURY / CognitiveKernel (manager):** interprets the user request once, forms the typed goal, owns constraints/uncertainty, assigns work, monitors results, decides whether to retry/escalate, and creates the single final response.
2. **Agent contract:** a typed `AgentTask` containing task ID, objective/capability, bounded inputs, dependency IDs, success conditions, and authority scope. A typed `AgentResult` returns status (`success`, `partial`, `blocked`, `needs_input`, `failed`, `timeout`), output, evidence/provenance references, and errors.
3. **Agent registry:** distinct from `Tool` registry. Each registered specialist declares its capabilities, allowed tools/services, supported task types, resource budget, and whether it is read-only. Unknown capabilities fail closed.
4. **Scoped specialist modules:** initially one `DataAgent` around existing dataset profiling/analysis capability, followed by a read-only verifier if the first slice proves useful. Future research/development specialists can reuse existing services/tools rather than duplicate them.
5. **Governed execution adapter:** specialists must not call arbitrary registered `tool.fn` functions or perform side effects around the runtime. Tool actions are passed through the central validation, policy, approval, and verification path. A reviewer has no write surface.
6. **Shared substrate:** one loaded Arabic-Retrieval model instance, one canonical Memory/MemoryController path, and the existing learning store. Agents receive validated `SemanticFrame`/`GoalSpec` and bounded evidence; they do not each reload the embedding model or independently reinterpret the user's raw message.
7. **Local execution first:** sequential delegation first. Add bounded parallel scheduling only after dependency, shared-state, approval, resource-conflict and timeout tests pass. Only independent, explicitly parallel-safe, non-approval work may run concurrently.

Suggested first-cut package boundaries (names are proposals, not claims about existing files):

```text
app/agents/
  contracts.py       # AgentTask / AgentResult / capability and status contracts
  base.py            # small specialist protocol
  registry.py        # specialist registration and capability matching
  data_agent.py      # delegates through existing governed data tools/services
  verifier.py        # independent read-only result checks
  dispatcher.py      # bounded agent invocation; no policy bypass
```

Keep `CognitiveKernel` as the decision-maker and make its integration with the dispatcher explicit. Do not put the whole system into one huge `kernel.py`, but also do not split every small utility into an independent agent.

## Small implementation plan and acceptance gates

### G0 — Architecture and baseline (current audit; no code changes)

**Accept when:** the source snapshot is identified; actual canonical runtime paths are documented; model-backed test baseline is reproducible; memory revision and approval-default failures have tracked tests; the current pre-change suite's pass/fail/blocker state is recorded.

### G1 — Contract and registry only

Add the minimum typed task/result contract and a registry for one inert/fake agent. No real tools, no new database, no parallelism.

**Accept when:** schema validation, duplicate agent IDs/capabilities, unknown capability, malformed result, timeout and exception paths are covered; existing architecture/security tests remain green; no new provider/LLM imports; Arabic retrieval constant and single-load behavior unchanged.

### G2 — First real specialist: DataAgent

Route one clear request such as “profile this CSV” through the manager to the DataAgent, reusing `profile_dataset` / `analyze_dataset` rather than duplicating data-analysis logic.

**Accept when:** valid data produces reproducible outputs and evidence; missing/ambiguous path asks for clarification or fails explicitly; invalid data returns a bounded error; the agent cannot write arbitrary workspace files; tool policy and verification still execute centrally; same request remains usable through the canonical interface.

### G3 — End-to-end orchestration and QA

Have SHURY create a small typed DAG: select/profile dataset → run requested analysis → independent read-only verification → final response. Start serially.

**Accept when:** dependencies and result references are validated; failure/partial status propagates; verification can block false completion; evidence sources appear in results; no internal task envelope leaks to the user; run is bounded by step/timeout limits.

### G4 — Second specialist only where demonstrated useful

Add ResearchAgent or DevelopmentAgent after DataAgent shows a verified end-to-end benefit. Use existing RAG/research or development tools under capability scopes.

**Accept when:** a cross-specialist workflow passes; specialists cannot expand each other's permissions; conflicts, missing evidence and unsupported requests fail closed.

### G5 — Concurrency is a separate gate

Do not include fan-out in the first slice. Later, schedule only ready, explicitly parallel-safe work with no approval requirement or resource conflict; merge outcomes deterministically and isolate each task's transient context.

**Accept when:** barrier-based concurrency tests, cycle/deadlock tests, cancellation/timeout tests, deterministic repeated trials, state-isolation tests and the complete regression suite pass.

## Non-negotiables retained

- No operational dependency on any LLM; no LLM fallback.
- Keep `omarelshehy/Arabic-Retrieval-v1.0` as the designated semantic model; it is for retrieval/semantic matching, not execution authority or response generation.
- No sentence-specific hardcoded agent routing. Routing should use explicit capability contracts and grounded typed goals, with conservative abstention when no match is qualified.
- No duplicate persistent memory or learning store per agent.
- No specialist may bypass central approval, runtime policy, verification or provenance.
- Build one verified vertical slice first, then expand based on evidence.

## Files reviewed most closely

- `app/api.py`
- `app/brain/kernel.py`
- `app/brain/models.py`
- `app/brain/capabilities.py`
- `app/brain/methods.py`
- `app/brain/planner.py`
- `app/runtime/cognitive_agent.py`
- `app/runtime/agent.py`
- `app/runtime/registry.py`
- `app/runtime/policy.py`
- `app/runtime/verify.py`
- `app/intelligence/semantic/retrieval.py`
- `app/intelligence/task_compiler.py`
- `app/domain/task_ir.py`
- `app/domain/task_graph.py`
- `app/planning/scheduler.py`
- `app/tools/data/analysis.py`
- `app/services/data_analysis_service.py`
- `docs/V23_STRICT_TODO.md`
- `docs/V23_IMPLEMENTATION_REPORT.md`
- Relevant architecture, security, cognitive-loop, task-planning and concurrency tests.
