# SHURY Phase 3 — Canonical Memory Data Model

Status: implemented and verified.

## Canonical logical record

The durable memory contract is represented by `app.knowledge.memory_models.MemoryRecord` with the canonical fields:

`id`, `memory_type`, `owner_id`, `scope`, `session_id`, `run_id`, `key`, `value`, `normalized_value`, `source`, `source_ref`, `confidence`, `importance`, `created_at`, `updated_at`, `valid_at`, `invalid_at`, `expires_at`, `revision`, `status`, `supersedes_id`, `metadata`.

## Storage compatibility

Existing SQLite storage remains intact. Historical physical column names are preserved and mapped explicitly:

- `kind` -> `memory_type`
- `normalized` -> `normalized_value`

No legacy rows are silently reclassified or assigned to a user during Phase 3.

## History

`memory_history` now keeps an ownership/scope/session/run/status snapshot for new history events, preserving provenance context across corrections and superseding revisions.

## Schema registration

SQLite records canonical schema metadata as `personal-agent.memory` version `3` in `memory_schema_meta`.

The existing export identifier `personal-agent.memory.v1` is retained for compatibility; exports additionally declare `memory_schema` and `memory_schema_version`.

## Deliberate Phase boundaries

Phase 3 does not define or enforce the strict memory-type policy, perform the legacy-data migration campaign, redesign retrieval, or modify the Brain.
