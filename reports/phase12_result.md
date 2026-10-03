# SHURY — PHASE 12 RESULT

## Status

**GATE: BLOCKED_BY_ENVIRONMENT**

Phase 12 is **not closed**. The 1000-conversation acceptance gate cannot pass until the required production dependency and model are available.

## Required execution

The phase contract requires execution of the actual SHURY runtime with the real `omarelshehy/Arabic-Retrieval-v1.0` model, Brain, Memory, Tools, RAG, research, verification, and learning, with isolated persistent state per conversation and full internal traces.

## Baseline / blocker

Production model preflight was executed in `SHURY_NLP_MODE=required`.

Observed:

```text
model = omarelshehy/Arabic-Retrieval-v1.0
loaded = false
error = RuntimeError: Arabic retrieval model unavailable: ModuleNotFoundError: No module named 'sentence_transformers'
```

An environment-only dependency installation attempt was also performed and failed because the environment could not resolve the package index / DNS. No alternate model was installed and no runtime fallback was counted.

A filesystem search found no installed `sentence_transformers` package and no cached Arabic-Retrieval model weights.

## Canonical runtime proof

The production entry path is:

```text
app.api.run_brain
    -> CognitiveKernel.act
        -> CognitiveKernel.think / execution pipeline
```

Before Phase 12 execution is accepted, the canonical semantic layer must successfully load `omarelshehy/Arabic-Retrieval-v1.0`.

A direct `run_brain(..., SHURY_NLP_MODE=required)` probe now fails closed with the same missing-dependency error. This removed a prior silent fallback in `CognitiveKernel.perceive()`.

## Phase 12 runner

Added:

```text
app/evaluation/real_dialogue_runner.py
scripts/run_real_dialogues.py
tests/test_phase12_real_runtime.py
```

The runner is designed to:

- preflight the real model in required mode;
- refuse execution if the model is unavailable;
- execute `CognitiveKernel.act` for every turn;
- preserve persistent state across turns inside one conversation;
- isolate Memory, Learning, RAG, Research, Network and Skills backends per conversation;
- persist complete `CognitiveState.trace` and state snapshots per turn;
- retain oracle comparisons without exposing traces through the user-facing response layer.

## Corpus

The Phase 10 deterministic corpus was validated before execution:

```text
sessions = 1000
turns = 3216
unique conversation IDs = 1000
multi-turn sessions = 1000
```

## Full Gate invocation

Command executed:

```text
PYTHONPATH=. SHURY_NLP_MODE=required python scripts/run_real_dialogues.py \
  --limit 1000 \
  --output reports/phase12_gate_execution
```

Result:

```text
exit_code = 2
status = BLOCKED_BY_ENVIRONMENT
executed_sessions = 0
```

No conversation was falsely counted as executed.

## Architectural changes in Phase 12

1. Required NLP retrieval errors now fail closed at the canonical Brain semantic boundary.
2. Research memory honors `AGENT_RESEARCH_DB`.
3. Network provenance/cache honors `AGENT_NETWORK_DB` and `AGENT_NETWORK_CACHE`.
4. `LearningStore` honors `AGENT_LEARNING_DB` when no explicit path is supplied.
5. `SkillBank` honors `AGENT_SKILLS_DB` when no explicit path is supplied.
6. The real-runtime runner uses a separate durable state directory for each conversation.
7. The runner records full internal traces only as benchmark artifacts, not in normal user responses.

## Tests

```text
Phase 12 focused suite: 14/14 PASS
Python compileall:      PASS
```

The focused suite covers strict retrieval failure propagation, canonical `run_brain` fail-closed behavior, corpus readiness, deterministic session IDs, per-conversation backend isolation, and the exact-1000 execution invariant.

## Final status

**BLOCKED_BY_ENVIRONMENT**

Phase 12 remains open. The code changes required for a real 1000-conversation run are in place, but the required Arabic-Retrieval-v1.0 runtime dependency/model is unavailable in the current execution environment.
