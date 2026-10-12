# PHASE 11 — HYBRID MEMORY RETRIEVAL

## Contract

Memory retrieval uses deterministic multi-signal fusion after ownership/scope filtering.
Security eligibility is decided before semantic, lexical, temporal, or ranking signals are computed.

### Signals

1. Semantic similarity through the existing local `Arabic-Retrieval-v1.0` sentence-retrieval path when available.
2. BM25-style lexical relevance.
3. Exact key match.
4. Entity overlap.
5. Character n-gram similarity for typo/paraphrase tolerance.
6. Temporal validity/relevance.
7. Confidence.
8. Importance.
9. Recency.
10. Canonical memory-type retrieval priority.

### Fusion

The weights are fixed and deterministic:

- semantic: 0.30
- lexical: 0.22
- exact_key: 0.18
- entity: 0.08
- character: 0.06
- temporal: 0.05
- confidence: 0.04
- importance: 0.03
- recency: 0.02
- type: 0.02

If the semantic model is unavailable, the remaining active weights are renormalized deterministically. Retrieval does not fail solely because the optional semantic signal is unavailable.

### Security gate

Candidates are filtered before scoring by exact `scope`, `owner_id`, `session_id`, and `run_id` where applicable. There is no hidden `global` fallback inside the retrieval scorer.

Recency and importance can only rank eligible candidates; they cannot create a match for unrelated or unauthorized memory.

### Temporal determinism

Each retrieval operation uses a single timestamp snapshot for recency calculations so repeated queries over the same snapshot are deterministic.

### Compatibility

`Memory.retrieve()` and the Phase-1 compatibility API `search_memory()` continue to expose the same result shape. Phase-11 adds signals without introducing a second memory authority.
