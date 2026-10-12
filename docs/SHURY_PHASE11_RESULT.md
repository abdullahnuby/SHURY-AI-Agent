# SHURY Phase 11 — Experience Replay Learning

## Objective

Turn the existing persistent prioritized replay index into an actual non-executing learning mechanism. Replay reuses historical experience without pretending that the environment was observed again and without executing tools.

## Design

1. `PrioritizedReplayBuffer` selects important historical transitions using the existing priority signals.
2. `ExperienceReplayLearner` samples a bounded batch and groups selected transitions by historical episode.
3. A selected episode is replayed as a real historical sequence through the existing `ValueModel` using TD(lambda)+SARSA.
4. Replay uses an importance-sampling correction factor derived from the current prioritized distribution.
5. Replay updates learned values but does **not** increment transition observation counts, value visit counts, or empirical return samples.
6. Replay writes a durable `replay_updates` audit record.
7. The current real execution is excluded from its own replay batch.
8. No planner, tool, runtime side effect, or external execution is called by replay.

## Why sequence replay

The current value learner already performs temporal credit assignment across complete observed trajectories. Replaying an entire historical episode preserves that sequence structure instead of treating every sampled transition as an isolated terminal event. Sequence replay is also an established replay variant for improving reuse of temporally related experience. citeturn565978academia1

## Importance weighting

Prioritized replay intentionally samples important experience more often than uniform replay. The learner records an approximate sampling probability and normalized importance weight so the tabular value update can reduce sampling bias. This follows the role of prioritized replay described by Schaul et al., while remaining deliberately simple and inspectable for SHURY's current tabular architecture. citeturn565978academia0

## Data model

### `replay_updates`

- batch_id
- transition_id
- episode_id
- sampling_probability
- importance_weight
- learning_rate_scale
- td_signal
- state_value_delta
- action_value_delta
- status
- error
- created_at

The table is an audit ledger, not a second memory system.

## Integration point

After real reward/prediction-error/model/value/policy updates in `SelfImprovementManager.observe_run()`, SHURY runs one bounded historical replay batch:

`replay_learning`

Then it records:

`policy_replay_update`

The replay stage is learning-only; it cannot execute a historical action.

## Behavioral guarantee

For a second real execution with prior history available:

- a historical replay is performed;
- replay_count increases;
- replay_updates receives an audit row;
- transition observation counts only reflect real observations;
- empirical value visit counts only reflect real observations;
- learned values can change due to replay;
- `side_effects_executed == 0`.

## Verification

Phase 11 focused regression after the final dependency-order cleanup: **21 passed**.

Repository regression after the final cleanup: **481 passed, 1 existing legacy failure**. The remaining failure is `tests/test_v8.py::test_parallel_ready_steps_are_executed_concurrently`, where the existing runtime invokes the test tool four times while the legacy assertion expects two. Phase 11 replay code does not execute tools and is not responsible for this failure.

Compilation: **PASS**.

## Boundary

Phase 11 does not introduce a new transition model, new planner, neural network, cloud database, or execution authority. It extends the existing replay/value architecture.
