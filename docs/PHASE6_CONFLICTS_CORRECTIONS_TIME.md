# PHASE 6 — Conflicts, Corrections, and Time

Phase 6 adds a deterministic temporal/conflict contract without deleting prior truth.

## Operations

- `remember(...)` — ADD or versioned UPDATE
- `update(...)` — versioned update
- `correct(...)` — versioned correction
- `supersede(...)` — explicit supersession of a selected revision
- `expire_memory(...)` — explicit expiration with an effective timestamp
- `forget_memory(...)` / `forget(...)` — explicit forgetting; history is retained
- `restore_history(...)` — restore an old revision as a new revision
- `memory_history(...)` — append-only operation history

## Temporal semantics

A durable memory revision can carry `valid_at`, `invalid_at`, and `expires_at`.
When a later revision supersedes an earlier one, the earlier revision receives an
`invalid_at` equal to the new revision's `valid_at` when supplied; otherwise the
change timestamp is used. The earlier row remains stored with its original value.

`retrieve_as_of(query, as_of, ...)` evaluates the historical validity interval at
`as_of`, so superseded/deleted rows may still be returned for periods in which they
were true. Ranking recency is anchored to the requested `as_of` timestamp.

`memory_timeline(...)` exposes all revisions for a key or selected memory and
`memory_history(...)` exposes the operation events and their timestamps.

## Forget and restore

Forgetting changes current availability but does not erase the historical row or
its history event. Restoring an old revision creates a new revision and records a
`RESTORE` event rather than resurrecting the old row in place.

## Security

All temporal operations resolve the active owner/scope/session/run context before
reading or writing. A different owner's historical revision cannot be restored,
expired, or retrieved through an incompatible context.
