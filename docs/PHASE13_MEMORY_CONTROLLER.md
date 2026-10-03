# PHASE 13 — MEMORY CONTROLLER → BRAIN

## Contract

```text
SEMANTIC FRAME
  → MEMORY REQUIREMENT
  → MEMORY CONTROLLER
  → SCOPED RETRIEVAL
  → STRUCTURED MEMORY EVIDENCE
  → BRAIN
```

`MemoryController` is the only retrieval boundary Brain needs. Storage details remain below `app.knowledge.memory`.

## Structured evidence

`MemoryEvidence` carries:

- memory type
- content
- confidence
- relevance
- source
- reference
- provenance
- non-authoritative metadata

`MemoryEvidenceBundle` carries the semantic `MemoryQueryPlan`, selected stores, logical scope, and typed evidence.

## Brain boundary

`CognitiveKernel.retrieve()` consumes `MemoryEvidenceBundle.to_brain_evidence()` and no longer calls `recall_context()`, `profile()`, or `get_fact()` directly for retrieval. The controller owns those storage operations.

The existing `Evidence` type remains the Brain-facing compatibility representation; personal memory continues to use `kind=memory`, while knowledge uses `kind=knowledge_memory`.

## Scope

The controller never weakens Phase 2 ownership/scope rules. It passes the caller context to the canonical Memory authority, and the controller only selects logical lanes from the semantic requirement.
