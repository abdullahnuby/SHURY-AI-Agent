# SHURY V23 — Strict Cognitive Architecture Execution Board

## Non-negotiable execution rules

1. V22 is frozen as the execution substrate. It is not allowed to grow cognitive routing logic.
2. The V23 core must not import an LLM provider. Model-backed paths stay outside the core and opt-in only.
3. A response patch is not accepted when the underlying cognitive state / planning behavior is missing.
4. Every milestone needs: source implementation + automated acceptance tests + runtime smoke evidence.
5. No milestone is marked DONE from code inspection alone.
6. Learning is allowed to change planning only from verified runtime evidence; synthetic examples are priors, never truth.
7. Failure, abstention and uncertainty are first-class outcomes. The system must not convert them into fake success.
8. Internal runtime envelopes, task IDs and planner dumps must never become user-facing answers.

## Architecture target

```text
Input
  ↓
Perception
  ↓
Semantic Frame
  ↓
Cognitive State
  ├─ Beliefs / Evidence / Discourse
  ├─ Goals / Constraints
  ├─ Hypotheses / Uncertainty
  └─ Self Model
  ↓
Deliberation
  ↓
Capability Graph + Methods
  ↓
State-Aware Planning / Search
  ↓
Execute
  ↓
Observe + Verify
  ↓
Belief Revision / World Update
  ↓
Replan when necessary
  ↓
Learn from verified experience
  ↓
Answer from conclusion + evidence
```

## Master board

| Milestone | Status | Required implementation | Gate |
|---|---|---|---|
| V23.0 | DONE (alpha) | persistent beliefs, revision metadata, provenance, contradiction event | `test_belief_revision_preserves_history_event` |
| V23.1 | DONE (alpha) | deterministic semantic frame, typed references, semantic transfer tests | `test_v23_semantic_transfer.py` |
| V23.2 | DONE (alpha) | goal formation + deterministic inference + evidence selection | `test_brain_v23_architecture.py` / `test_cognitive_kernel.py` |
| V23.3 | DONE (alpha) | capability contracts independent of language + candidate grounding | capability discovery tests |
| V23.4 | DONE (alpha) | MethodRegistry + method scoring + state-fact satisfaction filtering | `test_method_planner_and_state_filter_keep_unsatisfied_suffix` |
| V23.5 | DONE (alpha) | observed failure → state change → replan → alternative action | `test_runtime_failure_triggers_observation_conditioned_replan` |
| V23.6 | DONE (alpha) | verified experience reinforcement + multi-step procedure induction | `test_verified_experience_changes_future_method_grounding` + procedure test |
| V23.7 | DONE (alpha) | explicit self model with observed reliability and limits | `test_self_model_surfaces_observed_limits` + capability query smoke |
| V23.8 | DONE (alpha) | centralized semantic/result realizer; no internal JSON leakage | `test_brain_never_returns_internal_json_as_response` + browser smoke |
| V23.9 | TODO | curated training curriculum, positive/negative pairs, transfer benchmark, corpus provenance | training release gate |
| V23.10 | TODO | domain packs: development, research, data, web, personal; ontology + methods + verifiers | per-domain gate |
| V23.11 | IN PROGRESS | remove remaining legacy semantic dependencies from default V23 path; browser default + recovery | browser end-to-end gate + dependency audit |

## Current implementation slice — V23.0 → V23.8

### State and belief system

- [x] `app/brain/models.py`: explicit Belief/Evidence/CognitiveState.
- [x] `app/brain/store.py`: durable SQLite belief store.
- [x] revision/supersession metadata.
- [x] explicit `belief_revision` cognitive event when a belief changes.
- [ ] contradiction manager that can keep competing beliefs when sources conflict instead of forcing one active value.
- [ ] temporal validity / expiry as first-class belief constraints.

### Perception and discourse

- [x] language-independent operation concepts for supported core tasks.
- [x] typed `it` handling for `what time is it?`.
- [x] typed `this/that` handling using prior session goals.
- [x] unresolved deictic reference becomes a planning uncertainty, not an action.
- [x] semantic transfer benchmark for Arabic/English paraphrases.
- [ ] compositional sentence graph for arbitrary multi-clause requests.
- [ ] temporal/discourse relations beyond a single previous goal.

### Goal and inference

- [x] explicit GoalSpec.
- [x] hypothesis generation.
- [x] evidence ranking and query aliases.
- [x] self/capability goal.
- [ ] generic rule engine beyond current high-value predicates.
- [ ] contradiction resolution and belief revision policy.

### Capability and methods

- [x] capability contracts derived from Tool contracts.
- [x] MethodRegistry separated from semantic parsing.
- [x] method scoring using cost + verified experience.
- [x] semantic capability beats lexical noise.
- [ ] external method loading from declarative procedure files.
- [ ] parameterized methods with explicit applicability boundaries.

### Planning and execution

- [x] state-fact satisfaction filtering.
- [x] multi-step dependency dataflow.
- [x] observed output → world fact update.
- [x] verification gate rejects `abstained` / ungrounded answer results.
- [x] failure → alternative plan search.
- [ ] explicit conditional branches (`if / unless / otherwise / until`) with predicate evaluation.
- [ ] bounded search across multiple candidate plans, not only method choice.
- [ ] resource/risk-aware plan selection in the V23 layer.

### Learning

- [x] verified experience storage.
- [x] future tool selection can use verified experience.
- [x] multi-step procedure family induction.
- [x] failure lessons recorded.
- [ ] boundary learning: where a procedure must NOT be used.
- [ ] counterexample-driven revision.
- [ ] replay benchmark: does the learned procedure transfer to a new phrasing/state?

### Self model

- [x] capability inventory.
- [x] observed reliability by capability/tool.
- [x] observed low-reliability boundaries.
- [ ] confidence calibration benchmark.
- [ ] explicit “known / unknown / impossible with current tools” model.

### Conversation realization

- [x] centralized result realizer.
- [x] evidence-aware answers.
- [x] internal JSON/task envelope suppression.
- [ ] language planning independent of operation-specific branches.
- [ ] answer style based on user request and confidence.
- [ ] concise explanation of why SHURY chose a source/action when useful.

## V23.9 — Training curriculum (not started)

- [ ] build a provenance-tagged corpus directory.
- [ ] separate facts, procedures, preferences, examples and counterexamples.
- [ ] add paraphrase families where wording is withheld from evaluation.
- [ ] add state perturbations to test transfer.
- [ ] add failure/recovery trajectories.
- [ ] add refusal/abstention examples.
- [ ] release a fixed benchmark that the model cannot see during curriculum generation.

## V23.10 — Domain packs (not started)

Each domain pack must contain:

```text
ontology/
capabilities/
methods/
validators/
failure_modes/
examples/
benchmark/
```

### Development
- [ ] repository inspection
- [ ] test/build validation
- [ ] diagnosis
- [ ] low-risk repair
- [ ] post-repair verification

### Research
- [ ] source discovery
- [ ] evidence extraction
- [ ] source quality scoring
- [ ] conflict detection
- [ ] evidence-grounded synthesis

### Data
- [ ] dataset identification
- [ ] schema profiling
- [ ] quality checks
- [ ] statistical analysis
- [ ] reproducible result verification

### Web
- [ ] navigation/search
- [ ] fetch/read
- [ ] source freshness
- [ ] provenance
- [ ] bounded retry/recovery

### Personal
- [ ] identity
- [ ] preferences
- [ ] plans/tasks
- [ ] meetings/reminders
- [ ] contradiction and supersession

## V23.11 — Full migration

- [x] browser chat defaults to V23 kernel.
- [x] browser task state is recoverable after polling/network failure.
- [x] UI does not freeze forever on task failure/timeout.
- [ ] remove V22 semantic routing from all default code paths.
- [ ] migrate remaining V22 cognitive utilities into V23 modules or explicitly classify them as substrate adapters.
- [ ] dependency audit proving V23 core remains LLM-free.

## Acceptance command for every development slice

```powershell
py -m compileall app
pytest -q tests/test_v23_semantic_transfer.py tests/test_v23_cognitive_loop.py tests/test_brain_v23_architecture.py tests/test_cognitive_kernel.py tests/test_chat_runtime.py tests/test_chat_recovery.py tests/test_task_ir.py tests/test_task_planning_core.py tests/test_hotfix_imports.py
```

Current measured result after the V23.0–V23.8 slice:

```text
44 passed
```

A browser smoke must additionally prove:

```text
POST /api/chat → 202
GET /api/tasks?id=... → completed
state.final_message is human text
GET /api/session?session_id=... → recoverable state
```

## Current release decision

**V23.0.0-alpha1 is a real cognitive-core milestone, not a production-ready autonomous agent.**

The core now has one state/goal/capability/method/observation/learning loop. The remaining work is explicitly listed above and cannot be declared done without its gates.
