# SHURY Phase 14 — Memory Migration

## Governing scope

This document covers the **memory-architecture Phase 14** defined in the SHURY memory reconstruction plan. It is intentionally separate from the repository's pre-existing Phase 14 production-hardening work.

## Migration contract

Legacy memory is migrated only after:

1. a SQLite backup is created;
2. source counts are recorded;
3. each record is classified;
4. ownership/scope is checked;
5. placeholders and invalid records are identified;
6. global personal facts are quarantined;
7. benchmark/seed data is never interpreted as personal memory;
8. unknown ownership remains `owner_id=NULL` and `status='unresolved'`.

No legacy row is assigned to `local-default` merely because the runtime has a default owner.

## Canonical target

Legacy `facts` become `memory_items.kind='fact'`.
Legacy `notes` become `memory_items.kind='note'`.

Until ownership is explicitly resolved:

```text
scope = user
owner_id = NULL
status = unresolved
```

These records are therefore excluded from active user retrieval.

Historical `fact_history` rows are preserved as canonical fact revisions when possible. Each migrated row carries explicit legacy provenance in `metadata` and `source_ref`.

## Existing global personal memory

Any legacy-derived `fact`/`note` already present with `owner_id=NULL` and `scope=global` or `global_system` is quarantined to:

```text
scope = user
owner_id = NULL
status = unresolved
```

The previous scope is retained in metadata.

## Idempotency

A completed migration run is recorded in:

- `memory_migration_meta`
- `legacy_memory_migration_runs`
- `legacy_memory_migration_records`

Running the migration again returns the completed run instead of importing duplicate rows.

## CLI

```bash
python scripts/migrate_legacy_memory.py --db app/data/memory.db --dry-run
python scripts/migrate_legacy_memory.py --db app/data/memory.db
```

## Safety

The migration never deletes the original legacy tables. It records classification and migration decisions, and the pre-migration SQLite backup is created before the migration transaction begins.
