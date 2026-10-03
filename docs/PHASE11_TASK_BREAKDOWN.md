# Phase 11 Task Breakdown

- [x] Replace replay-as-index-only with an executable learning pass.
- [x] Preserve real-observation accounting during replay.
- [x] Add prioritized sampling probabilities and importance weights.
- [x] Replay historical sequences through the existing TD(lambda)+SARSA learner.
- [x] Prevent replay of the current execution within the same learning cycle.
- [x] Persist replay audit events in the existing LearningStore.
- [x] Integrate replay automatically into the online learning cycle.
- [x] Add behavioral tests for value change, evidence-count preservation, exclusion, and cycle integration.
- [x] Verify the full 482-test repository regression in split groups.
