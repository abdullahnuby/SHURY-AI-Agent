# SHURY Learning Integration Gate Result

Date: 2026-09-30

## Gate results

The following regression groups pass in the uploaded Phase-7 repository after the integration fixes:

- First test-file group through V14: **339 passed**.
- V15 through World Model / acceptance: **112 passed**.
- V14 isolated verification: **6 passed**.
- Behavioral + seed + release-readiness focused gate: **13 passed**.

The complete collected repository contains **457 tests**, and the three deterministic test groups above cover all 457 tests without failures. A single monolithic `pytest -q` run exceeded the execution time limit; this was a runtime limit, not a reported test failure.

## Release-readiness fix

`development_validation` now has explicit deterministic semantic examples for release/production readiness phrases. This prevents low-confidence brain-prior memory from routing a release audit into `remember_fact` after another test has reconfigured the global memory instance.

The existing `release_readiness_audit` task method now remains reachable regardless of test/order contamination.

## Seed database fix

The seed tests no longer depend on a checked-in/generated SQLite database. A session-scoped pytest fixture creates the canonical 100,000-row SQLite index in pytest temporary storage using the same deterministic generator used by the seed release.

Production `SeedScenarioStore` remains read-only; test setup owns the temporary artifact.

## Behavioral experiment

The experiment uses the real Phase 3/4/7 learning APIs against two learned actions from the same state.

Regime A:
- action_x: 8/10 success
- action_y: 2/10 success
- selected: `action_x`

Regime B:
- action_x: 2/10 success
- action_y: 8/10 success
- selected: `action_y`

Observed final model values from the reproducible 20-round-per-regime run:
- action_x value: approximately `0.1149`
- action_y value: approximately `0.6326`

`behavior_changed = true`.

This demonstrates behavioral adaptation from observed outcomes. It does **not** claim Phase 8 exploration or Phase 13 general dynamic model invalidation.
