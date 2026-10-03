# SHURY — PHASE 14 ROOT CAUSE ANALYSIS

## Scope
Root-cause analysis only. No production code, semantic rules, test expectations, or runtime behavior were modified during Phase 14.

## Evidence boundary
Phase 12 did not execute the required 1,000 real production conversations because `omarelshehy/Arabic-Retrieval-v1.0` could not be loaded in the environment. Therefore these RCA findings are based on the current executable test traces, targeted canonical-runtime traces, and the Phase 13 failure inventory. They are not mislabeled as 1,000-real-dialogue findings.

## Major RCA clusters

### RC-MEM-01 — Identity recall is demoted to generic memory

**Failures:** F13-CK-001

**Observed behavior:** `انا مين؟` produces `requested_operation=query_memory`; the Brain decision is `respond` with `answer_source=beliefs` even though the user name is present in canonical Memory.

**Expected behavior:** The semantic frame should represent an identity recall (`query_identity`) and the decision should identify the answer as coming from canonical memory.

**Root cause:** `SemanticInterpreter.parse()` contains an explicit identity rule that promotes `انا مين؟` to `recall_fact`, but `extract_slots()` does not emit the required `recall:key=name` slot for that form. `CognitiveKernel.perceive()` then normalizes `recall_fact` to `query_identity` only when the canonical `key` is `name`; with the key missing it falls back to `query_memory`. This is a semantic-slot-to-Brain-operation dependency failure, not a missing-memory-data failure.

**Architectural layer:** Semantic slot extraction → Semantic → Brain contract → decision routing.

**Files / functions:**
- `app/intelligence/semantic/slots.py` — `extract_slots()`
- `app/intelligence/semantic/parser.py` — `SemanticInterpreter.parse()`
- `app/brain/kernel.py` — `CognitiveKernel.perceive()`
- `app/brain/deliberation.py` — `deliberate()`

---

### RC-MEM-02 — Canonical memory evidence is represented as `belief`, not the legacy `memory` view

**Failures:** F13-CK-002

**Observed behavior:** `متى الاجتماع؟` returns the correct value and contains canonical memory-derived evidence, but `result.state.memories` contains `Evidence(kind='belief')` rather than `kind='memory'`.

**Expected behavior:** The public/compatibility memory view expected by the existing Brain test should expose the canonical memory evidence under the `memory` kind.

**Root cause:** `rank_beliefs()` uses `belief_to_evidence()`, which deliberately emits `Evidence(kind='belief')`. `CognitiveState.memories` only translates `legacy_memory` to `memory`; it does not translate canonical `belief` evidence. The data is retrieved correctly; the failure is the V22/V23 evidence-schema compatibility boundary.

**Architectural layer:** Brain evidence model / compatibility projection.

**Files / functions:**
- `app/brain/inference.py` — `belief_to_evidence()`, `rank_beliefs()`
- `app/brain/models.py` — `CognitiveState.memories`

---

### RC-SOC-01 — Arabic social classification is broken by normalization/pattern mismatch

**Failures:** F13-CK-003

**Observed behavior:** `ايه الأخبار؟` becomes `query_knowledge` and the Brain returns `research` instead of a direct conversational response.

**Expected behavior:** The utterance is classified as social small talk and handled by the conversational response path without research/planning.

**Root cause:** `normalize()` removes the alef/hamza distinction and converts `الأخبار` to `الاخبار`. `_explicit_social_turn()` tests the normalized text against a pattern containing `إيه\s+الأخبار|ايه\s+الأخبار`, which does not match the normalized form. Because the explicit social detector returns no match, later generic-question/fresh-data inference promotes `knowledge_query`, and `deliberate()` therefore selects research.

**Architectural layer:** Arabic normalization → social classification → answer-policy precedence.

**Files / functions:**
- `app/intelligence/understanding.py` — `normalize()`
- `app/intelligence/semantic/parser.py` — `_explicit_social_turn()`, `SemanticInterpreter.parse()`
- `app/intelligence/answer_policy.py` — `infer_knowledge_question_candidate()`
- `app/brain/deliberation.py` — `deliberate()`

---

### RC-RES-01 — Generic factual questions are blocked by a false unresolved copular pronoun

**Failures:** F13-CK-004

**Observed behavior:** `ما هو الثقب الأسود؟` receives a `query_knowledge` semantic operation, but the semantic frame contains `anaphoric_reference_unresolved`; Brain deliberation returns `clarify` before the research decision.

**Expected behavior:** The phrase `هو` in this Arabic copular construction should not be treated as a discourse reference requiring antecedent resolution. The question should proceed to evidence-seeking research.

**Root cause:** `REF_PATTERNS` treats standalone `هو` as a generic pronoun. `resolve_references()` has safeguards for English expletive `it`, but no corresponding Arabic grammatical/context distinction for copular `هو`. The resolver therefore manufactures an unresolved reference; `CognitiveKernel.perceive()` preserves it correctly, and `deliberate()` intentionally gives unresolved-reference uncertainty precedence over research.

**Architectural layer:** Reference resolution / semantic uncertainty → Brain decision precedence.

**Files / functions:**
- `app/intelligence/semantic/references.py` — `resolve_references()` / `REF_PATTERNS`
- `app/brain/kernel.py` — `CognitiveKernel.perceive()`
- `app/brain/deliberation.py` — `deliberate()`

---

### RC-RES-02 — `open_world_learning` has no matching deliberation operation branch

**Failures:** F13-CK-004 (learning form), F13-CUI-001

**Observed behavior:** `learn how to improve` is parsed as `requested_operation=open_world_learning`. The planner can construct an exploration plan, but the final Brain decision is `clarify`. The Web serializer accurately exposes that `clarify` decision.

**Expected behavior:** The open-world learning request should select the research/learning decision path when an evidence-seeking plan exists.

**Root cause:** The semantic layer emits the operation name `open_world_learning`, and planning produces an information-gathering plan for that capability, but `deliberate()` explicitly handles `learning_intent` and does not handle `open_world_learning`. The operation therefore falls through to the generic final `clarify` branch. F13-CUI-001 is a presentation of this Brain decision, not an independent Web serialization root cause.

**Architectural layer:** Semantic operation vocabulary → Brain deliberation/planning contract.

**Files / functions:**
- `app/intelligence/semantic/parser.py` — semantic operation production for `open_world_learning`
- `app/brain/planner.py` — `plan()` / exploration planning path
- `app/brain/deliberation.py` — `deliberate()`
- `app/interfaces/web/server.py` — `serialize_state()` (symptom reporter, not root cause)

---

### RC-PLAN-01 — Natural-language calculation loses the canonical `expression` slot before planning

**Failures:** F13-CK-005

**Observed behavior:** `احسب 25 * 16` produces `requested_operation=calculate` and slot `operation:expression=25 * 16`, but the Brain plan is empty and decision is `clarify`.

**Expected behavior:** The canonical Brain frame must contain `expression=25 * 16`, enabling the calculator method to construct an executable action.

**Root cause:** The structured-goal adapter already defines the required mapping `operation:expression → expression`, but `CognitiveKernel.perceive()` only normalizes selected memory namespaces and does not apply the same calculation-slot mapping. `app/brain/methods.py::_calculate()` requires `frame.slot('expression')`; because the slot is absent, the builder returns no action, so deliberation has no executable plan and returns `clarify`.

**Architectural layer:** Semantic → Brain contract → Planning method applicability.

**Files / functions:**
- `app/brain/kernel.py` — `CognitiveKernel.perceive()`
- `app/brain/structured.py` — `validate_structured_goal()` (reference contract proving the intended mapping)
- `app/brain/methods.py` — `_calculate()`
- `app/brain/planner.py` — `plan()`
- `app/brain/deliberation.py` — `deliberate()`

---

### RC-VER-01 — Learning evidence is downstream of missing execution transitions

**Failures:** F13-LI-001, F13-LI-002

**Observed behavior:** Calculation `act()` completes with no `learning_recorded` event and no persisted learning experience for the run.

**Expected behavior:** A successfully executed calculation should generate a verified transition, record a `learning_recorded` event, and persist the run experience.

**Root cause:** `CognitiveKernel._execute_result()` invokes `learning.observe_run()` and emits `learning_recorded` only when `learning_transitions` exist. The current calculation does not produce a plan/action because RC-PLAN-01 occurs upstream, so `learning_transitions` remains empty. The learning store itself is not the primary root cause of these two failures; they are downstream consequences of the planning/execution contract failure.

**Architectural layer:** Planning → execution transition production → verification/learning lifecycle.

**Files / functions:**
- `app/brain/kernel.py` — `_execute_result()` (learning lifecycle gate)
- `app/brain/planner.py` — `plan()` (no executable plan)
- `app/brain/methods.py` — `_calculate()` (returns no action without `expression`)

**Dependency:** RC-VER-01 depends on RC-PLAN-01 for the observed test scenario.

---

### RC-RUN-01 — Aggregate test time exceeds the execution harness window; isolated tests terminate

**Failures:** F13-RUN-001, F13-RUN-002

**Observed behavior:** Phase 13 recorded two aggregate pytest timeout/non-termination observations. Current isolated evidence is different: `test_chat_ui_regressions.py` terminates in 9.98s with one assertion failure, and `test_explicit_human_correction_reuses_previous_assignment_key` terminates individually in 10.65s. A clean subset of eight memory tests also terminates in 11.18s.

**Expected behavior:** Aggregate test execution should finish within the available execution window and provide a complete result.

**Root cause:** The Phase 13 observations are process/harness-level timeout observations, not reproducible application deadlocks in the isolated cases. The memory file is a long serial suite containing multiple `run_agent()` integrations; cumulative execution exceeds the available command/tool window. The chat file's current standalone run terminates normally, so its earlier timeout is likewise attributable to the aggregate execution environment rather than a persistent Web application deadlock.

**Architectural layer:** Test execution orchestration / runtime environment, not SHURY semantic architecture.

**Files / functions:**
- `tests/test_memory_v22_full.py` — aggregate suite; heavy legacy `run_agent()` integration tests
- `tests/test_chat_ui_regressions.py` — aggregate suite
- `app/runtime/agent.py` — `run_agent()` (contributing runtime cost in the legacy test path)

**RCA status:** Root cause identified as an execution-window/harness constraint; no Phase 14 code fix performed.

---

### RC-ENV-01 — Required production NLP dependency/model is unavailable

**Failures:** F13-RUN-003 / Phase 12 Gate blocker

**Observed behavior:** Production-required mode refuses to execute because `sentence_transformers` is missing; `transformers` is also unavailable and no `omarelshehy/Arabic-Retrieval-v1.0` model cache is present. Dependency installation could not complete because package-index DNS resolution was unavailable.

**Expected behavior:** The required production retrieval runtime must load `Arabic-Retrieval-v1.0` before any real conversation can be counted.

**Root cause:** Environment provisioning is incomplete: required Python packages and model weights are absent and network/package-index access is unavailable. This is an environment root cause, not a SHURY code defect. The production adapter correctly fails closed rather than substituting another model.

**Architectural layer:** Production environment / model provisioning.

**Files / functions:**
- Production retrieval adapter: current canonical Arabic-Retrieval loading path (observed through strict `run_brain()` preflight)
- Environment/package layer: `sentence_transformers`, `transformers`, model cache/network availability

**RCA status:** Environment blocker remains open from Phase 12. No substitute model or LLM is permitted.

---

## Cross-cluster dependency map

```text
RC-MEM-01 ─┐
           └→ Memory identity routing
RC-MEM-02 ───→ Memory evidence compatibility

RC-SOC-01 ───→ Social classification / research avoidance

RC-RES-01 ───→ Generic research questions
RC-RES-02 ───→ Learning/research deliberation

RC-PLAN-01 ──→ Calculation execution
        │
        └────→ RC-VER-01 (downstream learning/verification evidence)

RC-RUN-01 ───→ Test orchestration/runtime evidence
RC-ENV-01 ───→ Phase 12 production execution availability
```

## RCA conclusion

Every major current Phase 13 failure cluster has an identified root cause at a concrete architectural or environment boundary. No Phase 15 fix has been applied in this phase.
