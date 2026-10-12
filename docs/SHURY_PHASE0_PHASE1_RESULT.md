# SHURY — Phase 0 + Phase 1 Architectural Result

## Scope

This document records the repository audit required before cognitive implementation and the completed Phase 1 changes. Phase 2+ learning infrastructure was intentionally not implemented.

## 1. Current architecture assessment

### Runtime entry points

- `app/api.py` exposes `CognitiveKernel().act(...)` as the V23 brain path.
- `app/brain/__main__.py` directly runs `CognitiveKernel`.
- `app/runtime/agent.py` contains the broader legacy/runtime executor, replanning, checkpointing, and tool execution path.
- `app/runtime/react.py` is a separate LLM-capable runtime path and is not the target non-LLM cognitive core.

### V23 brain

- `app/brain/perception.py` performs deterministic semantic parsing into `SemanticFrame`.
- `app/brain/inference.py` provides deterministic hypotheses/belief ranking.
- `app/brain/capabilities.py` converts registered tools into capability candidates.
- `app/brain/planner.py` is the active planner used by `CognitiveKernel` and applies existing experience priors.
- `app/brain/deliberation.py` turns cognitive state into a governed decision.
- `app/brain/kernel.py` orchestrates the V23 path.
- `app/brain/store.py` persists beliefs and cognitive events.
- `app/brain/learning.py` stores V23 experiences and simple procedure candidates.
- `app/brain/self_model.py` already exposes runtime reliability information.

### Existing world model

- `app/domain/world.py` contains the mutable explicit `WorldState` and deterministic transition application.
- `app/world/model.py` predicts consequences from tool contracts and compares prediction against actual state diffs.
- `app/world/store.py` persists a session-scoped world snapshot.
- `app/tools/system/world.py` exposes read-only action simulation.
- `tests/test_world_model.py` and `tests/test_world_model_acceptance.py` already validate persistence, read-only simulation, structured deltas, and prediction comparison.

### Existing learning/evaluation

- `app/learning/*` is a second, broader self-improvement system with `LearningStore`, `ExperienceRecord`, `ReplayEvaluator`, promotion/rollback, and skill evolution.
- `app/brain/learning.py` is a separate V23 experience store with a narrower schema.
- `app/evaluation/*` contains unit/acceptance/benchmark infrastructure, including self-improvement and world-model benchmarks.

## 2. Existing capabilities that can be reused

- `SemanticFrame`, `GoalSpec`, `CandidateAction`, `PlannedAction`, and `Decision` are already established V23 cognitive contracts.
- `WorldState` already models facts, variables, capabilities, resources, entities, relations, observations, uncertainties, history, and fingerprints.
- `WorldModel` already provides deterministic consequence prediction from tool contracts, actual observation capture, and prediction-vs-observation comparison.
- `BrainExperienceStore` and `LearningStore` already persist experience; no new generic memory database is required.
- Existing runtime validation, approvals, permissions, certificates, and verification remain the execution authority.

## 3. Components that must be extended

### Extended in Phase 1

- `app/brain/models.py`
  - added `CanonicalState`
  - added `ActionSpec`
  - added `Transition`
  - added deterministic canonicalization/fingerprinting helpers
  - added `CognitiveState.to_canonical_state()`
  - added `CognitiveState.action_specs`
- `app/domain/world.py`
  - added explicit slots for constraints, environment conditions, temporal context, and learned state features
  - included them in snapshots for backward-compatible persistence
- `app/world/model.py`
  - exposes the new explicit world-state dimensions through model context
- `app/brain/kernel.py`
  - builds `ActionSpec` objects from existing candidates
  - emits a canonical-state checkpoint event after planning

## 4. Components that must NOT be duplicated

- Do not create another memory store beside the existing `app/brain/store.py`, `app/brain/learning.py`, and `app/learning/store.py` without a consolidation decision.
- Do not create another execution/orchestration engine beside `CognitiveKernel` and the existing governed runtime.
- Do not create another world-state store; reuse `app/world/store.py`.
- Do not create another planner. The repository currently contains two planning families (`app/brain/planner.py` and `app/planning/*`); this is an existing architectural convergence problem, not something Phase 1 should multiply.
- Do not replace `app/world/model.py` with a parallel transition predictor.
- Do not introduce an LLM into the V23 brain path.

## 5. Missing cognitive primitives before Phase 1

Before this change, state/action information existed across several domain objects but there was no single stable canonical contract containing all decision-relevant dimensions required by the target architecture.

The missing pieces were:

- a text-independent canonical state identity;
- a single structured action operator containing parameters, preconditions, effects, risk, cost, reversibility, historical counters, expected reward, and uncertainty slots;
- a transition boundary explicitly separating state-before, predicted state, actual state, outcome, reward, verification, and prediction error.

Phase 1 adds these contracts without implementing learning algorithms.

## 6. Proposed data model

### CanonicalState

The canonical state is composed from the current cognitive/world state and contains:

- facts
- variables
- entities
- relations
- capabilities
- resources
- active goals
- constraints
- pending actions
- completed actions
- failures
- environment conditions
- temporal context
- uncertainty
- bounded observations
- relevant historical state
- learned state features

It deliberately does **not** include raw user text or session identifiers.

### ActionSpec

Each decision-relevant action is represented as a transition operator with:

- stable instance identifier
- semantic capability
- tool
- parameters
- preconditions
- expected effects
- risk
- cost
- reversibility
- execution-time slot
- historical success/failure counters
- expected reward slot
- uncertainty

Historical/reward fields remain neutral until later learning phases populate them with evidence.

### Transition

A transition stores references to canonical state fingerprints and keeps prediction separate from actual observation. It can carry outcome, reward, prediction error, verification, timestamp, and machine metadata.

## 7. Proposed learning loop

Phase 1 establishes the contracts needed by the target loop:

`OBSERVE → REPRESENT STATE → ... → GENERATE ACTIONS`

The repository's later phases can attach retrieval, predictive transition learning, value updates, replay, policy updates, and self-model updates to these stable contracts without changing state identity.

Phase 1 itself does not claim that this loop is already learned end-to-end.

## 8. Interfaces introduced

- `CanonicalState.to_dict()` / `CanonicalState.fingerprint()`
- `ActionSpec.to_dict()` / `ActionSpec.signature()` / `ActionSpec.from_candidate(...)`
- `Transition.to_dict()` / `Transition.fingerprint()` / `Transition.from_states(...)`
- `CognitiveState.to_canonical_state()`

## 9. Database/schema changes

No new database or migration was introduced in Phase 1.

The explicit new `WorldState` fields are snapshot-compatible and use defaults when older snapshots do not contain them.

This is intentional: persistence/experience infrastructure belongs to Phase 2, not Phase 1.

## 10. Dependency graph

```text
User/Input
   |
   v
app/brain/perception.py
   |
   v
SemanticFrame
   |
   +--> app/brain/inference.py ----> Hypotheses
   |
   +--> app/brain/capabilities.py -> CandidateAction
   |                                      |
   |                                      v
   |                                ActionSpec (Phase 1)
   |
   +--> app/brain/planner.py ------> PlannedAction
   |
   v
CognitiveState
   |
   +--> WorldState (app/domain/world.py)
   |       |
   |       +--> app/world/model.py -> prediction/observation
   |       +--> app/world/store.py -> persisted session world
   |
   +--> CanonicalState (Phase 1)
   |       |
   |       +--> deterministic fingerprint
   |       |
   |       +--> Transition (Phase 1)
   |
   v
app/brain/deliberation.py
   |
   v
Decision
   |
   v
Governed runtime / execution
```

## 11. Migration strategy

1. Keep current V23 domain objects intact.
2. Add canonical adapters instead of replacing them.
3. Treat canonical fingerprints as the new stable state identity at the cognitive-contract boundary; later phases should use them for experience/model keys.
4. In Phase 2, persist transition records through the existing experience infrastructure or a deliberately consolidated store.
5. In later phases, attach learned transition/value/replay logic to these interfaces.
6. Only after behavioral evidence exists should the two existing planning families be converged.

## 12. Phase-by-phase implementation status

| Phase | Status |
|---|---|
| Phase 0 — deep audit + dependency map | **DONE + verified** |
| Phase 1 — canonical State / Action / Transition | **DONE + verified** |
| Phase 2 — experience + replay infrastructure | **NOT DONE** |
| Phase 3 — empirical transition model | **NOT DONE** |
| Phase 4 — reward/value model | **NOT DONE** |
| Phase 5 — prediction error/confidence | **NOT DONE** |
| Phase 6 — counterfactual simulator | **Existing deterministic world simulation exists, but not yet upgraded to learned counterfactual simulation** |
| Phase 7+ | **NOT DONE** |

## 13. Behavioral experiments

Existing repository experiments already cover:

- deterministic world prediction from tool contracts;
- exact prediction comparison against observed state diffs;
- read-only action simulation;
- session-world persistence/isolation;
- self-improvement/skill-evaluation behavior.

New Phase 1 tests add:

- order-invariant deterministic canonical fingerprints for unordered state dimensions;
- text/session independence of canonical state identity;
- stable action signatures independent of parameter dictionary order and instance id;
- transition separation of predicted and actual state fingerprints.

The required learning experiments from the transformation specification are not yet claimed as passed because the learned transition/value/replay stack has not been implemented.

## 14. Evaluation metrics

The target metrics remain those in the transformation specification. Phase 1 can reliably expose state/action/transition identities, but it does not yet produce learned measurements such as model accuracy, prediction-error learning curves, exploration efficiency, transfer rate, or catastrophic forgetting.

## 15. Risks and failure modes

1. **Two planner families remain.** The architecture currently has both the V23 brain planner and the older/general planning package. Further work should converge ownership rather than add another planner.
2. **Two learning stores remain.** `BrainExperienceStore` and `LearningStore` both exist. Phase 1 intentionally avoids introducing a third store, but Phase 2 should decide whether they are unified or clearly separated by responsibility.
3. **LLM-capable runtime remains in the repository.** `app/runtime/react.py` and `app/world/model.py` can use provider-backed paths, but the Phase 1 canonical cognitive contracts themselves are non-LLM. The target non-LLM brain should remain isolated from these optional paths.
4. **Canonical state includes decision-relevant ordering where required.** Pending action order is preserved because execution order can change behavior; unordered dimensions are normalized for fingerprints.
5. **No learning is implied by data structures alone.** The presence of `historical_*`, `expected_reward`, or `learned_features` fields does not mean they are learned yet.

## Verification

Targeted regression suite after Phase 1:

`31 passed`

The full repository suite was additionally exercised. The two known baseline-heavy suites were not treated as Phase 1 acceptance gates because their fixtures/environment are incomplete or flaky independently of this change.

Also verified with Python bytecode compilation:

`python -m compileall -q app tests`
