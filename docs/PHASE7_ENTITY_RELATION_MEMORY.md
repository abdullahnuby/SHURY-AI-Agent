# Phase 7 — Entity and Relation Memory

## Canonical entity identity

Entities now have one deterministic canonical identity plus aliases inside an exact memory scope. Resolution accepts either the canonical identity or an alias and never falls back across users, sessions, or runs.

## Relation model

Relations persist:

- subject entity id
- predicate
- object value
- scope
- owner/session/run context
- confidence
- validity interval
- source memory id
- revision
- supersedes id
- provenance metadata

Exact duplicate active relations are idempotent. Explicit corrections create a new revision, mark the previous revision `superseded`, and preserve the prior truth for historical queries.

## Historical graph queries

`graph(..., as_of=...)` evaluates relation validity at the requested timestamp. Current graph queries expose only active, currently-valid relations.

## Safety boundary

Entity and relation lookup uses the same ownership/scope context model as canonical memory. No benchmark namespace or global fallback is used as a substitute for production ownership.

## Compatibility

Existing `upsert_entity()` and `relate()` APIs remain wrappers around `link_entity()` and `link_relation()`.
