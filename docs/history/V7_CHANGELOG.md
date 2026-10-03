# V7 Changelog

## Implemented

- Replaced stage/first-match planning with bounded best-first capability search.
- Added explicit Tool contracts: capability, preconditions, produces, cost,
  risk, idempotence and parallel safety.
- Added durable runtime runs/checkpoints/effects to SQLite.
- Added `resume_agent(run_id)` using the persisted plan and state.
- Added exact `replay_run(run_id)` for effect inspection with no execution.
- Added bounded automatic replacement planning after tool failure.
- Added objective-level completion verification.
- Added world-state capability facts and last-result propagation.
- Added selective forgetting capability and memory benchmark categories.
- Preserved old public APIs/tests where practical.

## Validation

Run `python -m pytest -q`.
