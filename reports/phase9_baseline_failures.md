# SHURY Phase 9 — Bilingual Conversation Baseline

## Scope
Bilingual stateful conversation: Arabic, English, Arabic→English, English→Arabic, Arabic-English mixed, Egyptian Arabic, MSA, technical English inside Arabic.

## Baseline environment
- `SHURY_NLP_MODE=off` was used for deterministic fallback tests because the Phase 0 environment cannot load `Arabic-Retrieval-v1.0` dependencies.
- Canonical runtime exercised through `run_cognitive()` and direct `CognitiveKernel` probes.
- No source code was changed before this report was written.

## Existing suite baseline
- `tests/test_semantic_contract.py`: 3/3 PASS
- `tests/test_semantic_layer2.py`: 13/13 PASS
- `tests/test_semantic_real_user.py`: 19/19 PASS
- Phase 8 reference regression was previously closed at 8/8 PASS.

## Harness/environment failures
1. Aggregate pytest command timed out before producing a trustworthy matrix. Not counted as a behavioral pass/fail.
2. Temporary bilingual harness initially failed from `/tmp` with `ModuleNotFoundError: No module named 'app'`; rerun with `PYTHONPATH=.` succeeded and is not counted as a SHURY product failure.

## Stateful bilingual baseline failures
### B01 — Arabic memory statement false clarification
Conversation:
- `أنا اسمي عبدالله` → `needs_user`, no tool.
Expected: `MEMORY_WRITE` and durable memory write.
Observed semantic cause: Arabic attached-clitic resolver falsely extracted `ه` from the person name `عبدالله`.

### B02 — Arabic MSA city question wrong route
- `أين مدينتي؟` → `needs_user`
- `Where am I from?` → completed memory read.
Expected: both should preserve the same memory intent across language switch.
Observed semantic cause: Arabic `أين/فين + مدينتي` was not covered by the generic city-memory question contract.

### B03 — Arabic→English previous-task continuation loses executable route
- `راجع المشروع` → completed `inspect_project`
- `Check it` → `needs_user: goal_or_capability`
Expected: English continuation resolves the same project task and routes to the corresponding development capability.
Observed cause: resolved reference reached `reference_target=project`, but the generic follow-up operation was allowed to override the previous task capability with `development_git`, leaving no executable GoalSpec.

### B04 — English→Arabic task-deictic continuation loses context
- `review the project` → completed
- `راجع المهمة دي` → `needs_user: goal_or_capability`
Expected: Arabic task deictic preserves the previous English goal.
Observed cause: semantic reference resolution did not survive the full `run_cognitive()` boundary into an executable operation.

### B05 — Egyptian Arabic memory-profile → English recall misroutes
- `فاكر اسمي؟` → completed memory retrieval
- `What do you remember about me?` → clarification with `research_status` candidate.
Expected: both turns remain on the memory authority/path after language switch.
Observed cause: English memory-profile intent was not normalized into the canonical Brain memory-query route in the natural-language runtime path.

### B06 — Mixed technical Arabic-English loses intent
- `أنا عاوزك تعمل code review للـ project` → clarification
- `Now inspect it` → completed `inspect_project`.
Expected: mixed-language turn should preserve the technical development intent and establish context for the English continuation.
Observed cause: mixed semantic routing produced no concrete development intent for the Arabic+technical-English utterance.

## Language-state finding
The canonical semantic layer currently stores `language` per `SemanticParse`, but `WorldState` has no canonical persisted `last_language` field. Response selection therefore depends on the current turn only. Phase 9 will determine and test whether explicit language state must be persisted to preserve bilingual continuity without changing user-request language.

## Phase 9 gate status
OPEN — baseline recorded, source changes now permitted.
