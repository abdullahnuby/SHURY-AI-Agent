# SHURY Runtime Map — Phase 1 Baseline

## Phase 1 status

**PHASE 1 RESULT**

- Implemented: runtime map documented from source inspection and live execution traces.
- Tests: CLI and Web live path probes executed with `SHURY_NLP_MODE=off` solely to make the runtime executable in the current environment where the required model dependency is absent.
- Failures: multiple active entry paths use different runtimes; this is an architecture finding, not a hidden failure.
- Blocked: production NLP model unavailable in the environment, so a model-backed live semantic trace could not be obtained.
- Gate: **PASS** — every inspected user-message entry path is mapped.

## 1. Repository entry points

### Python module entry points

- `app/main.py`
  - imports `app.interfaces.cli.main`
  - executes the interactive CLI.
- `scripts_run_shury_ui.py`
  - imports `app.interfaces.web.server.main`
  - starts `ThreadingHTTPServer` and `Handler`.
- `app/brain/__main__.py`
  - creates `CognitiveKernel`
  - invokes `kernel.think(...)` by default or `kernel.act(...)` with `--act`.
  - This is a direct Brain CLI/demo path, separate from `app/main.py`.

## 2. CLI execution paths

### `python app/main.py` → `app.interfaces.cli.main()`

The CLI imports `run_agent` directly from `app.runtime.agent`.

Natural user input, after slash-command dispatch, reaches:

```text
USER MESSAGE
  ↓
app.interfaces.cli.main
  ↓
(no slash command matched)
  ↓
app.runtime.agent.run_agent
  ↓
legacy/mature understand + semantic_understand + planner/decision/executor
  ↓
app.runtime.response.compose_final_response
  ↓
CLI output
```

### CLI `/agent <goal>`

Source dispatch explicitly imports `app.runtime.cognitive_agent.run_cognitive`:

```text
/agent <goal>
  ↓
app.interfaces.cli.main
  ↓
app.runtime.cognitive_agent.run_cognitive
  ↓
SemanticInterpreter.parse
  ↓
CognitiveKernel.act_structured
  ↓
Brain
  ↓
CLI output
```

### CLI clarification continuation

When `run_cognitive` returns `needs_user`, the next normal CLI input is appended to the prior cognitive goal and sent to `run_cognitive` again.

### CLI `/semantic <text>`

This is a parser-only path:

```text
/semantic <text>
  ↓
app.interfaces.cli.main
  ↓
app.intelligence.semantic.semantic_understand
  ↓
structured semantic output
  ↓
CLI
```

It does **not** execute the Brain or tools.

### CLI `/brain`

This command reports Brain/NLP status. It does not accept and execute a user message.

## 3. Web execution paths

`app.interfaces.web.server.Handler.do_POST()` is the HTTP user-message boundary.

### `POST /api/chat`

Task creation is followed by `_run_task(...)` in a daemon thread.

Default configuration:

```text
POST /api/chat
  ↓
Handler.do_POST
  ↓
_run_task
  ↓
run_brain(message, ...)
  ↓
app.api.run_brain
  ↓
CognitiveKernel.act
  ↓
Brain semantic/perception → retrieval → planning/decision → execution/verification/learning
  ↓
serialized task state + final_message
  ↓
GET /api/tasks
  ↓
Web UI
```

Runtime switch behavior found in `_run_task`:

1. `SHURY_USE_LEGACY_RUNTIME=1` → `app.api.run_agent` → `app.runtime.agent.run_agent`.
2. Else `SHURY_ENABLE_COGNITIVE_UI=1` → `app.api.run_cognitive` → `app.runtime.cognitive_agent.run_cognitive`.
3. Else (default) → `app.api.run_brain` → `CognitiveKernel.act`.

Therefore the Web layer contains three selectable execution routes, with `run_brain` as the default route.

### `POST /goal` and `/api/goal`

Structured goal path:

```text
POST /goal or /api/goal
  ↓
validate_structured_goal
  ↓
_run_structured_task
  ↓
app.api.run_structured_goal
  ↓
CognitiveKernel.act_structured
  ↓
Brain
  ↓
serialized task state + response
```

This is not a natural-language user-message parser; it is a structured GoalSpec interface.

### `POST /api/approval`

This is an approval/control path, not a new agent runtime:

```text
POST /api/approval
  ↓
ApprovalBroker.approve
  ↓
persistent memory approval record
  ↓
waiting execution in _run_task/_run_structured_task resumes
```

## 4. Direct Brain entry path

`python -m app.brain <message> [--act]` is a separate direct entry point:

```text
CLI arguments
  ↓
app.brain.__main__.main
  ↓
CognitiveKernel
  ↓
think()       # default
or act()      # --act
  ↓
Brain response
```

This bypasses `app.runtime.agent` and `app.runtime.cognitive_agent` wrappers entirely.

## 5. Public API entry points

`app/api.py` exposes:

- `run_agent` → imported directly from `app.runtime.agent`.
- `run_cognitive` → lazy wrapper around `app.runtime.cognitive_agent.run_cognitive`.
- `run_brain` → constructs/uses `CognitiveKernel` and calls `engine.act(...)`.
- `run_structured_goal` → constructs/uses `CognitiveKernel` and calls `engine.act_structured(...)`.

This file therefore exposes multiple orchestration entry points rather than a single canonical public runtime.

## 6. Runtime classification at Phase 1

### Current default natural-language runtime

- **Web `/api/chat`:** `app.api.run_brain` → `CognitiveKernel.act`.
- **CLI ordinary natural message:** `app.runtime.agent.run_agent`.
- **CLI `/agent`:** `app.runtime.cognitive_agent.run_cognitive` → Brain structured path.
- **Direct Brain CLI:** `CognitiveKernel.think/act`.

### Canonical runtime

**Current system does not have one cross-interface canonical runtime.**

For the Web default, the Brain path (`run_brain` → `CognitiveKernel`) is the active/default production natural-chat route. This is established by source dispatch and a live `/api/chat` trace.

### Legacy runtime

`app.runtime.agent.run_agent` is the mature/legacy orchestration runtime. Source comments explicitly describe it as the legacy runtime, and Web can activate it with `SHURY_USE_LEGACY_RUNTIME`.

### Duplicate/alternate runtime

`app.runtime.cognitive_agent.run_cognitive` is an alternate orchestration wrapper around the Brain. Web can activate it with `SHURY_ENABLE_COGNITIVE_UI`, and CLI `/agent` calls it directly.

### Direct/dead status

`app/brain/__main__.py` is live as an independent Python module entry point, but is not used by the Web server or `app/main.py` CLI.

## 7. Live trace evidence

### CLI live probe

Executed from repository root with `PYTHONPATH=.` and `SHURY_NLP_MODE=off`:

```text
/agent hello
/brain
hello
exit
```

Observed:

- `/agent hello` returned `I need: goal_or_capability`, confirming the `run_cognitive` route.
- `/brain` reported `"brain": "canonical-state-brain"` and semantic model name `omarelshehy/Arabic-Retrieval-v1.0` with mode `off` for this environment probe.
- ordinary `hello` returned `I need: goal_or_capability`, confirming the default CLI falls through to `run_agent` rather than `run_brain`.

### Web live probe

Server started on free port `8877` with `SHURY_NLP_MODE=off`.

`GET /api/health` returned the Brain subsystem as `canonical-state-brain` and identified `arabic-retrieval-v1.0` as the configured semantic model.

`POST /api/chat` with `{"message":"hello","session_id":"phase1-web"}` returned HTTP `202` with a task ID.

Polling `/api/tasks?session_id=phase1-web` returned a completed task whose cognitive state contained:

- semantic `requested_operation: "greeting"`
- decision `kind: "respond"`
- decision `answer_source: "conversation"`
- final message `"Hello. I'm SHURY."`
- cognitive trace entries for perception, retrieval, goal formation, planning, canonical state, and decision.

This is direct evidence that default Web `/api/chat` reaches the Brain path.

## 8. Architectural finding carried forward

The runtime map proves a Phase 2 issue:

```text
CLI natural message ─────→ legacy run_agent
CLI /agent ─────────────→ cognitive_agent → Brain
Web /api/chat default ─→ run_brain → Brain
Web optional flags ─────→ legacy OR cognitive_agent
Direct brain CLI ───────→ CognitiveKernel
```

The system is therefore **not yet one canonical runtime across all interfaces**. No fix is applied in Phase 1; this finding is intentionally carried into Phase 2.
