# SHURY Phase 9 — LLM-Independent Execution

## Scope

This phase implements the Phase 9 requirement from the Online Autonomous Brain migration specification: SHURY Core must continue executing, verifying, learning, and maintaining state when the language-model gateway is disabled or unavailable.

Source requirement: `Pasted markdown.md`, section 30 Phase 9 and section 14 LLM OFF behavior.

## Tasks

1. **Hard LLM-off switch** — `SHURY_LLM_MODE=off` disables the optional language gateway.
2. **Provider-unavailable fallback** — `run_cognitive()` falls back to the canonical `CognitiveKernel` instead of failing when no provider exists.
3. **Lazy optional cognition imports** — importing the cognitive runtime does not load the LLM provider or cognitive model layer until LLM mode is actually used.
4. **Canonical structured goal path** — `CognitiveKernel.act_structured()` and `app.api.run_structured_goal()` accept validated structured goals without natural-language model calls.
5. **Direct HTTP Goal API** — `POST /goal` and `POST /api/goal` run the canonical structured goal path asynchronously and report `llm_used=false`.
6. **Runtime policy boundary** — Brain execution now calls the existing deterministic `check_tool()` policy before running a tool.
7. **Runtime verification boundary** — Brain execution now uses the existing `verify_step()` contract after tool execution and records the verification result.
8. **Health evidence** — `/api/health` exposes that structured execution is available and reports whether the optional language gateway is `auto` or `disabled`.

## Execution path

```text
Natural language (optional)
        |
        v
Language Gateway (optional)
        |
        v
Structured Goal / deterministic Brain input
        |
        v
CognitiveKernel
        |
        +--> State / Experience / World Model / Planner / Value / Exploration
        |
        v
Policy validation
        |
        v
Tool execution
        |
        v
Deterministic verification
        |
        v
Reward / prediction error / transition / value / replay
```

When `SHURY_LLM_MODE=off`, the optional language branch is removed; the canonical execution path remains active.

## Verification

- 4 focused Phase 9 tests passed.
- Web/compatibility regression after the change: 37 tests passed; after structured web coverage: 8 tests passed in the combined focused group.
- Full repository was collected at 474 existing tests before adding Phase 9 tests. The first 355 existing tests passed as a group; the remaining 119 existing tests passed as a group. The Phase 9 test group passed as well.
- `python -m compileall -q app tests` passed.
- `import app.runtime.cognitive_agent` no longer loads `app.integrations.llm`.

## Behavioral proof

The Phase 9 test runs `run_cognitive()` with `SHURY_LLM_MODE=off` and an intentionally unusable provider object. The call is still executed by the canonical Brain, returns a completed result, and produces a learned transition in the canonical LearningStore.

The structured goal test executes `calculate` directly from structured input and produces a verified result plus a learning event without invoking any language gateway.

## Explicit non-goals

This phase does not add a new planner, new memory store, new database, or new learning algorithm. It does not move the online database described by the migration specification; that belongs to the later persistent-online-storage phases. It also does not connect a new LLM provider.
