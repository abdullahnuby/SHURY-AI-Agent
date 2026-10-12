# SHURY Learning Integration Gate Changelog

- Closed `CognitiveKernel` → Layer-5 learning integration.
- Fixed undefined `trajectory` use in `SelfImprovementManager.observe_run()` path.
- Unified `BrainExperienceStore` onto canonical `LearningStore`.
- Persisted Brain operation/task context in canonical experiences.
- Made Phase-7 model-based planning a default candidate in existing planner facades, with deterministic fallback.
- Passed shared learning manager and registry through the legacy runtime planner path.
- Added stale goal-parameter protection for learned model-based actions.
- Lazy-loaded optional LLM modules from public API/semantic parser paths.
- Added behavioral integration/regression tests covering the complete Brain learning loop, planner defaulting, single-store behavior, stale parameter safety, and LLM import isolation.

## Phase 9 — LLM-independent execution

- Canonical Brain execution remains available with `SHURY_LLM_MODE=off` or no provider.
- Structured goals bypass the optional language gateway and enter the same Brain learning path.
- Brain execution now enforces existing runtime policy and post-execution verification contracts.
