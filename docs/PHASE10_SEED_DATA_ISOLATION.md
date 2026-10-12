# PHASE 10 — Seed Data Isolation

## Purpose

The synthetic seed corpus is a benchmark/capability prior, not production knowledge.
It must never be treated as:

- user memory
- world/project knowledge
- execution evidence
- promotion evidence

## Classification

```text
source              = synthetic_seed
data_class           = benchmark
runtime_role         = capability_prior
authoritative        = false
not_user_memory      = true
not_execution_evidence = true
not_promotion_evidence = true
not_knowledge        = true
seed_version         = 100k-v1
```

The seed corpus is deterministic synthetic data generated from benchmark archetypes and
stored in `data/seed`. Its provenance remains attached to each scenario.

## Runtime policy

### SeedScenarioStore

`SeedScenarioStore` is read-only at the API level and SQLite `query_only` is enabled on
its connections. Invalid or missing seed provenance markers are rejected from `get()` and
`search()`.

### Learning

A seed bootstrap may create only `capability_priors` in the canonical `LearningStore`.
Those rows are explicitly classified as:

```text
origin_class = capability_prior
data_class   = benchmark
source_ref   = seed://100k-v1
```

Seed bootstrap does not create `experiences`, `procedural_memories`, or `lessons`.
The live influence is therefore an explicit architectural prior for semantic/capability
routing, not execution evidence or learned user knowledge.

### Knowledge / RAG

Synthetic seed content cannot be imported into the Phase 9 Knowledge Base. Attempts to
index a source marked `synthetic_seed` or `not_knowledge=true` are rejected.

Ordinary RAG answer synthesis excludes synthetic seed evidence. Seed evidence is only
eligible for explicit seed/benchmark/catalog questions. A dedicated catalog response is
also explicitly labeled as synthetic and non-authoritative.

### Cognitive context

The cognitive context may expose small seed examples as `synthetic_seed_examples`, but
these are marked as a read-only `capability_prior` and are kept separate from `memory`.
This is an intentional routing prior, not personal memory.

## Boundary guarantees

```text
SEED
 ├── benchmark corpus
 ├── capability prior ✅
 ├── user memory     ❌
 ├── knowledge/RAG   ❌
 ├── execution proof ❌
 └── promotion proof ❌
```

## Evidence

Phase 10 tests cover:

1. physical read-only seed storage
2. provenance marker validation
3. Knowledge Base rejection
4. ordinary-question answer-evidence exclusion
5. explicit seed-query detection
6. capability-prior-only bootstrap
7. cognitive-context classification
