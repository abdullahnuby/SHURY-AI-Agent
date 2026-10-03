# SHURY — PHASE 13 FAILURE COLLECTION

## Scope
Failure collection and clustering only. No production fixes or test weakening were performed.

## Evidence boundary
Phase 12 was blocked before real execution because `Arabic-Retrieval-v1.0` could not be loaded. Therefore there are **0 real-1000-runtime failures** to claim. This report separates current executable-test failures from historical/resolved evidence and the production environment blocker.

## Current open assertion clusters

| Cluster | Count | Representative failures |
|---|---:|---|
| Memory | 2 | identity answer source uses `beliefs`; memory question omits memory state item |
| Research | 2 | generic factual question clarifies instead of researching; `learn how to improve` clarifies instead of researching |
| Verification | 2 | learning trace not recorded; persisted learning experience missing |
| Social | 1 | Arabic small-talk enters research instead of direct response |
| Planning | 1 | actionable calculation clarifies instead of executing |

### Current process/environment cluster

| Cluster | Count | Meaning |
|---|---:|---|
| Runtime | 3 | two aggregate pytest non-termination observations + required NLP/model environment blocker |

## Required taxonomy — current primary counts

```text
Social          = 1
Intent          = 0
Entity          = 0
Slot            = 0
Reference       = 0
Memory          = 2
Context         = 0
Planning        = 1
Tool routing    = 0
Tool execution  = 0
Verification    = 2
RAG             = 0
Research        = 2
Security        = 0
Response        = 0
Runtime         = 3
```

Secondary overlaps are retained rather than double-counted in the primary table. Current overlap tags:

```text
Intent       = 3
Planning     = 3
Context      = 1
Response     = 2
Tool routing = 1
```

## Cluster details

### Memory
`test_identity_is_answered_from_memory` and `test_memory_question_is_semantically_reduced` both demonstrate that the Brain's memory answer/state representation is not aligned with the current canonical-memory contract.

### Research
The generic evidence question and `learn how to improve` both fail at research decision selection and currently terminate in clarification.

### Verification / Learning evidence
The learning integration tests expose missing learning transition evidence and missing persisted experiences after execution. These are treated as verification failures because the observable learning contract is not being proven.

### Social
`ايه الأخبار؟` is routed to research instead of a direct conversational response.

### Planning
`احسب 25 * 16` reaches clarification instead of executable planning.

### Runtime
Two suites show process-level non-termination when run as aggregates. Separately, production real-runtime execution is blocked before turn 1 because the required retrieval model/dependency cannot load.

## Historical / already-resolved evidence
These are retained for lineage but are **not current open clusters**:

- Phase 3 semantic expression normalization failure.
- Phase 4 reference/semantic-transfer failures.
- Phase 7 memory-authority divergence and forget/DI failures.
- Phase 8 reference-resolution failures.
- Phase 9 bilingual continuity/routing failures.
- Phase 11 structured representation mismatches discovered by the deterministic oracle.

They were subsequently covered by regression tests in their owning phases.

## Phase 13 rule
No individual failure has been patched during this phase. Root-cause analysis and fixes begin only after this clustering gate is accepted.
