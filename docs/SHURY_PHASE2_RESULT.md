# SHURY — Phase 2 Result

## Status

**Phase 2 — Experience and Replay Infrastructure: DONE + VERIFIED**

Phase 3 and later phases were **not started**.

## 1. Architectural decision

Phase 2 reuses the existing `app/learning/store.py` as the durable learning store.

No new memory database was introduced.

The existing `LearningStore.experiences` table remains the episode-level compatibility record. The new `transitions` field makes `run_id` the durable **episode id** and stores the real transition sequence captured from runtime effects.

The replay index is stored in the same `learning.db` as `replay_items`.

The older `app/brain/learning.py` / `BrainExperienceStore` remains a compatibility subsystem during the V23 migration. Phase 2 does not create a third learning store.

## 2. Episode model

`ExperienceRecord` now represents an episode-level trajectory and exposes:

- `episode_id` — alias of `run_id`
- existing goal/task/status/reward/verification fields
- existing summarized `steps`
- `transitions` — ordered serialized Phase-1 `Transition` records
- `meaningful` — identifies episodes with observed execution evidence

Older records without `transitions` remain readable and safely deserialize with an empty tuple.

## 3. Transition capture

`SelfImprovementManager.observe_run()` now converts the runtime's already persisted effect records into Phase-1 transitions.

Source:

`memory.effects(state.run_id)`

For each actual execution attempt, Phase 2 records:

- state-before fingerprint
- structured `ActionSpec`
- action parameters after deterministic secret/path sanitization
- tool capability
- tool preconditions/effects
- risk
- cost
- reversibility
- observed execution duration
- success/verification outcome
- failure category when applicable
- state-after fingerprint
- attempt number
- timestamp
- provenance metadata

Prediction is intentionally **left unset** at this phase. A learned predicted state and prediction-error update belong to Phase 3/5.

The captured state fingerprints currently originate from the governed runtime `WorldState`, so replay metadata explicitly marks them as:

`state_fingerprint_kind = "world"`

Phase 2 does not pretend these are learned canonical predictions.

## 4. Prioritized replay

`app/learning/replay.py` now contains `PrioritizedReplayBuffer`.

It is persistent, bounded, deterministic-capable, and strictly non-executing.

The replay priority retains the required evidence dimensions:

```text
prediction_error
novelty / rarity
failure_importance
uncertainty
learning_value
```

It also uses bounded boosts for:

```text
boundary transitions
contradictory evidence
```

The implementation keeps the raw priority components in the database rather than reducing them to one unexplained score.

Current component weights:

```text
prediction_error     0.36
novelty              0.20
failure_importance   0.18
uncertainty          0.12
learning_value       0.10
boundary bonus       0.02
contradiction bonus  0.06
```

These are replay-selection weights only. They are **not** a value function, reward model, or learned policy.

## 5. Replay categories

The replay API supports explicit views for the cases required by the specification:

- `prioritized`
- `recent`
- `high_error`
- `failures`
- `rare` / `novel` / `under_explored`
- `successful`
- `boundary`
- `contradictory`

Sampling is weighted without replacement using the stored priority and configurable exponent `alpha`.

Sampling marks transitions as replayed but does not execute actions.

## 6. Contradictory evidence

For repeated occurrences of the same state/action signature, the replay index compares outcome signatures.

When incompatible outcomes are observed, both the previous and current evidence are marked as contradictory and receive a bounded priority boost.

No prior experience is overwritten.

## 7. Bounded memory

`PrioritizedReplayBuffer` has a configurable capacity.

Default:

`5000 transitions`

Environment override:

`AGENT_REPLAY_CAPACITY`

When capacity is exceeded, the lowest-priority evidence is removed first. This prevents FIFO-only retention and preserves high-value learning evidence.

## 8. Runtime integration

The existing `SelfImprovementManager.observe_run()` path is now:

```text
runtime effects
      ↓
Episode / ExperienceRecord
      ↓
Phase-1 Transition records
      ↓
LearningStore
      ↓
PrioritizedReplayBuffer
      ↓
future learner consumption
```

Phase 2 does **not** update:

- world model parameters
- Q/V values
- policy
- exploration strategy
- self model
- procedures
- skills

Those remain later phases.

## 9. Safety boundary

Replay is evidence handling only.

`PrioritizedReplayBuffer` contains no tool invocation path.

Tests explicitly monkeypatch `Tool.run()` to fail if called during replay sampling.

No replay operation bypasses runtime policy, approval, permissions, verification, or certificates.

## 10. Database migration

Existing `learning.db` files are upgraded lazily.

The migration adds:

```text
experiences.transitions
```

and creates:

```text
replay_items
```

without deleting existing experiences or lessons.

## 11. Behavioral verification

Phase 2 tests verify:

1. legacy experiences remain readable;
2. episode transitions persist and round-trip;
3. replay remains bounded;
4. high-error and failure evidence receives higher replay importance;
5. contradictory outcomes are retained and prioritized;
6. replay sampling never executes tools;
7. required replay-category views work;
8. the existing runtime effect path produces actual replay transitions.

Targeted verification:

**7/7 Phase 2 tests passed**

Combined Phase 1 + Phase 2 + Layer 5 + V23/world-model regression set:

**42/42 passed**

Broader regression excluding the two known baseline groups completed:

**399 passed, 1 failed**

The single failure is an existing V8 parallel-execution expectation (`2` calls vs the current baseline behavior of `4`).

Separately excluded known baseline/environment failures:

- 8 seed-scenario tests require a populated `scenarios` database table that is absent from the supplied repository environment;
- 1 existing task-planning test expects `inspect_project → git_status → check_project` and currently receives an empty plan.

A full repository run was not used as the final gate because the complete suite exceeded the execution timeout in this environment.

## 12. Phase boundary

### Completed

- Phase 0 audit
- Phase 1 canonical state/action/transition contracts
- Phase 2 episode persistence
- Phase 2 transition capture
- Phase 2 persistent prioritized replay
- Phase 2 bounded retention
- Phase 2 category-aware replay views
- Phase 2 contradiction handling
- Phase 2 non-executing verification

### Not started

- Phase 3 empirical learned transition model
- Phase 4 reward/value model
- Phase 5 prediction error/confidence learning
- Phase 6 learned counterfactual simulator
- Phase 7 model-based planner
- later exploration/continual/meta/self-model phases

## Core result

SHURY now has a durable evidence substrate in which a real executed trajectory can become:

```text
Episode
  → ordered transitions
  → persisted evidence
  → transparent replay priority
  → bounded prioritized replay
```

It still does not claim to be learning from replay. The next phase must consume this evidence to build the empirical transition model rather than merely adding more storage.
