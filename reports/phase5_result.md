# SHURY — PHASE 5 RESULT

## Phase 5 Start

**Scope:** Conversation-vs-task classification and routing.

**Allowed files:** semantic classification/intent/slot/reference code, canonical runtime routing, direct regression tests, and `reports/`.

**Acceptance Gate:** Run at least 100 conversational inputs. Social turns must not unnecessarily enter planning.

## Baseline Failures Recorded Before Fixes

The initial Phase 5 focused baseline (`tests/test_chat_runtime.py`, `tests/test_semantic_contract.py`, `tests/test_semantic_real_user.py`, `tests/test_cognitive_kernel.py`) produced 33 passes / 4 failures. The four failures were recorded before any Phase 5 implementation changes:

1. Cognitive identity response used `beliefs` instead of `memory` as the answer source.
2. Cognitive memory question did not emit a `memory` state item.
3. Standalone Arabic small-talk was labeled `beliefs` instead of `conversation`.
4. Direct Brain calculation was classified as `clarify` instead of `execute`.

These remain outside the Phase 5 acceptance gate unless required by the Phase 5 routing boundary; they were not altered in this phase.

## Implemented

### 1. Canonical conversation-class precedence

`SemanticContract.conversation_class` is now the high-level classification boundary with the following precedence:

- `SOCIAL`
- `CLARIFICATION`
- `MEMORY_WRITE`
- `MEMORY_READ`
- `RESEARCH`
- `ANALYSIS`
- `INFORMATION`
- `EXECUTION`
- `TASK`

Clarification/reference uncertainty is no longer allowed to become execution. Plain informational questions are not promoted to execution merely because a fuzzy lower-level intent is noisy.

### 2. Canonical runtime consumes the conversation class

`run_agent()` now materializes `SemanticContract` and records the high-level class in the runtime trace. Standalone social turns are routed directly through the conversational response path before planning.

### 3. General semantic memory-write coverage

Added general semantic assignment coverage for language facts and `save/store/remember this information` constructions. These are capability-level slot patterns, not sentence-specific patches.

### 4. Social reference normalization

Standalone acknowledgements such as `got it` no longer become unresolved-reference clarifications. The reference layer recognizes discourse-level social phrasing as a complete turn.

### 5. Capability-information vocabulary

Added a first-class `query_capabilities` semantic route for English and Arabic capability questions.

## Regression Coverage

New file:

`tests/test_phase5_conversation_classification.py`

It contains exactly **100 deterministic conversational inputs** covering:

- 20 SOCIAL
- 20 MEMORY_WRITE
- 20 MEMORY_READ
- 20 INFORMATION
- 10 RESEARCH
- 5 ANALYSIS
- 5 EXECUTION
- 3 CLARIFICATION

The classification matrix executed **100/100 correctly**.

The runtime social-routing regression executed **20/20 social turns**, with a planner spy proving that the planner was called **0 times**.

## Tests

- Python compile: **PASS (exit 0)**
- Test collection: **PASS — 541 tests collected**
- Phase 5 + affected regression suite: **33 passed / 0 failed**
- Phase 5 classification matrix: **100 passed / 0 failed**
- Social runtime routing: **20 passed / 0 planner calls**

## Failures

Phase 5 acceptance failures after implementation: **0**.

The four baseline CognitiveKernel failures above remain recorded as pre-existing failures and were not modified because they are not required by the Phase 5 acceptance gate.

## Environment / Blocked

The Phase 0 production-model blocker remains unchanged:

- `sentence-transformers` / `transformers` are unavailable in the current environment.
- `Arabic-Retrieval-v1.0` therefore could not be production-loaded during Phase 0.
- No replacement or generative LLM was introduced.

## Changed Files In Phase 5

- `app/intelligence/semantic/contract.py` — canonical conversation-class precedence.
- `app/intelligence/semantic/intents.py` — capability-information semantic route.
- `app/intelligence/semantic/slots.py` — generalized fact assignment extraction.
- `app/intelligence/semantic/parser.py` — standalone social/reference handling.
- `app/intelligence/semantic/references.py` — discourse-level social memory phrasing handling.
- `app/runtime/agent.py` — canonical conversation-class routing and trace event.
- `tests/test_phase5_conversation_classification.py` — 100-input class gate and planner-bypass regression.
- `reports/phase5_collect.txt` — collection evidence.
- `reports/phase5_tests.txt` — affected regression evidence.
- `reports/phase5_result.md` — phase record.

## Gate

**PASS**

Phase 5 is closed. No Phase 6 implementation was started.
