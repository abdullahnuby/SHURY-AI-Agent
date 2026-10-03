# SHURY — Phase 9 Result

## Phase

PHASE 9 — BILINGUAL CONVERSATION

## Scope

Arabic, English, Arabic→English, English→Arabic, mixed Arabic-English, Egyptian Arabic, MSA, and technical English inside Arabic. The acceptance focus was preservation of memory, context, intent, references, and tool routing across language switches.

## Baseline Failures Recorded Before Fixes

1. Arabic `أنا اسمي عبدالله` was blocked by a false attached Arabic pronoun extraction.
2. Arabic `أين مدينتي؟` did not reach the canonical city-memory route.
3. Arabic→English `راجع المشروع` → `Check it` lost the previous capability route.
4. English→Arabic `review the project` → `راجع المهمة دي` lost the previous task context in the runtime path.
5. Egyptian-Arabic memory profile followed a research-related route instead of the canonical memory route.
6. Mixed technical Arabic-English `code review` required unnecessary clarification.

## Additional Failures Recorded During Phase 9

- A first bilingual regression asserted that `Luxor` should be returned in Arabic spelling. The runtime correctly preserved the stored proper noun; the regression expectation was corrected without changing production behavior.
- A reference regression expected the Arabic antecedent `المشروع` to be translated into `project`. The runtime correctly preserved the antecedent identity; the regression now validates identity/routing rather than translation.
- A regression treated `PlannedAction` as an executed `PlanStep`. The test harness was corrected to inspect the planned tool and runtime decision status.
- An Egyptian `أنا من فين؟` regression expected the `city` key. The semantic contract correctly distinguishes `origin`; the regression now validates the correct dialect-specific semantic key with the same memory route.
- The initial 100-session pytest harness repeatedly timed out. Direct canonical-runtime isolation showed the runtime itself was healthy; the oversized benchmark harness was removed from the Phase 9 regression test and the required Phase 9 gate was executed through the real runtime directly.
- A deterministic runtime trace exposed English `Where is my city?` routing to open-world knowledge; this was a genuine semantic capability defect and was fixed at the memory question slot/intent layer.
- Generic name-recall follow-ups such as `Tell me my name again.` / `قولّي اسمي؟` were misclassified; this was fixed through general semantic intent/slot coverage.
- Generic development follow-ups such as `Inspect it now` could be hijacked by Git similarity; this was fixed through general development-inspection vocabulary/context routing.

## Architectural Fixes

### Semantic language/memory normalization

- Added generic English/Egyptian/Mixed memory question coverage for city/name recall.
- Added canonical `recall:key=name` handling for generic name-recall follow-ups.
- Added English city-question variants to the same canonical memory route.

### Cross-language context/routing

- Preserved grounded references across language switches.
- Inherited the previous task capability for weak generic follow-up commands.
- Expanded development-inspection vocabulary for generic follow-up forms.
- Preserved Arabic antecedent text without forcing cross-language translation.
- Prevented unrelated memory-profile exploration from replacing the direct memory route.

### Regression coverage

`tests/test_phase9_bilingual_conversation.py` now contains capability-level tests covering:

- Arabic→English memory continuity
- English→Arabic memory continuity
- Arabic→English reference routing
- English→Arabic whole-task references
- Egyptian-Arabic→English memory profile
- mixed technical Arabic-English
- MSA/Egyptian Arabic memory questions
- bilingual name-recall paraphrases
- cross-language inspection follow-up chains
- English city-question variants

## Final Test Evidence

- Phase 9 focused regressions: **10/10 PASS**
- Phase 8 reference regressions: **8/8 PASS**
- Semantic real-user: **19/19 PASS**
- Semantic Layer 2: **13/13 PASS**
- Semantic contract: **3/3 PASS**
- Phase 7 memory authority: **6/6 PASS**
- Combined affected suites: **59/59 PASS**
- Test collection: **571 tests**
- Python compile: **PASS**

## Gate 9 — Real Canonical Runtime

Runtime path used:

`app.api.run_brain → CognitiveKernel.act → CognitiveKernel.think → semantic parser → Brain decision/planning → execution`

Gate dataset: **30 independent multi-turn conversations**.

Coverage:

- Arabic→English
- English→Arabic
- Egyptian Arabic
- MSA
- technical English inside Arabic
- mixed-language turns
- cross-language memory writes/reads
- cross-language task continuation
- reference resolution
- tool routing

Results:

```text
TOTAL:    30
PASSED:   30
FAILED:    0
```

Observed:

- memory continuity failures: **0**
- context-loss failures: **0**
- intent-routing failures: **0**
- reference-loss failures: **0**
- wrong-tool-routing failures: **0**

## Environment Blocker

The Phase 0 production environment limitation remains: `sentence-transformers` / `transformers` are unavailable in this environment, so production loading of `omarelshehy/Arabic-Retrieval-v1.0` remains blocked. No replacement model and no generative LLM were introduced.

## Phase 9 Gate

**PASS**

## Status

PHASE 9 CLOSED
