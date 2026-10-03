# Personal Agent Memory Architecture

## Purpose

The memory subsystem is a durable, local, provider-independent data layer for the agent. It is designed around separate memory lanes rather than a single notes table.

### Memory lanes

- **Working memory** — session-scoped transient context with priority and expiry.
- **Episodic memory** — raw interaction episodes with session/run provenance.
- **Semantic memory** — facts, preferences, goals and profile items with versioning.
- **Procedural memory** — repeated successful tool workflows promoted from experience.
- **Temporal memory** — validity windows (`valid_at`, `invalid_at`, `expires_at`) and historical revisions.
- **Graph memory** — entities and relations with provenance and temporal validity.

## Lifecycle

```text
observe
  → privacy gate
  → episodic record
  → explicit candidate extraction
  → semantic upsert / supersede
  → repeated-success workflow promotion
  → hybrid retrieval
  → access tracking
  → consolidation / cleanup / forgetting
```

Raw episodes and `memory_history` are preserved as evidence. Consolidation changes active state but does not erase the audit trail.

## Retrieval

Retrieval combines deterministic lexical signals (BM25-like score, phrase match, character similarity, entity overlap) with recency, importance, confidence, access frequency and lightweight diversity selection. Temporal validity and scope are hard filters, not ranking bonuses.

The current runtime deliberately has no embedding dependency. This makes the core memory deterministic and offline. The retrieval module is isolated so a future dense-vector provider can be added without changing storage or lifecycle semantics.

## Provenance and conflicts

Every durable item records source, source reference, revision and timestamps. Updates supersede the active revision instead of overwriting evidence. User-sourced facts outrank automatic confirmations when the values are equal.

## Forgetting

There are three distinct operations:

- **expire** — item is no longer temporally valid.
- **archive** — retention policy removes the item from active recall while preserving history.
- **forget/delete** — explicit user deletion; audit history remains minimal and does not keep the deleted value active.

`forget everything about me` is approval-gated.

## Security

Credential-like values are rejected from durable memory. Episodic text is redacted before persistence when it contains explicit credential assignments. Memory scopes are enforced on working memory, semantic retrieval and graph queries.

## Procedural learning

A successful run is not automatically promoted to a reusable procedure. The same normalized goal must succeed repeatedly; then the dominant tool sequence is stored as a procedural memory with evidence run IDs. This is a conservative local form of test-time learning.

## Evaluation

Run:

```text
/memory-benchmark
```

The benchmark covers static recall, dynamic updates, history preservation, episodic recall, working-memory scope, temporal expiry, procedural retrieval, provenance, selective forgetting, health, and exportability.

The benchmark is inspired by current agent-memory evaluation priorities, especially static/dynamic state, workflows, environment experience, accurate retrieval, long-range understanding, and selective forgetting.
