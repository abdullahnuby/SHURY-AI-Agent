# Personal Agent V16 Architecture — Adaptive RAG Portfolio

V16 keeps the model-free constraint while changing RAG from a fixed pipeline into a deterministic decision process.

```text
Query
  ↓
Query Profile
  ├─ length / decomposition
  ├─ structured cues
  ├─ comparative cues
  └─ temporal cues
  ↓
Strategy Portfolio
  ├─ Focused retrieval
  ├─ Broad retrieval
  ├─ Decomposed / multi-hop retrieval
  ├─ Neighbor navigation
  └─ Multi-strategy fusion
  ↓
Evidence Set Selection
  └─ greedy set-cover over query + subquery terms + source diversity
  ↓
Evidence Gate
  ├─ sufficient → extractive answer
  └─ insufficient → adaptive escalation
                    ↓
              marginal-gain stop
  ↓
Trace + provenance + latency
  ↓
Retrieval Experience Store
  └─ context-conditioned recency-weighted UCB
```

## Design principles

1. Current-corpus evidence outranks historical preference.
2. Retrieval is a decision; it is not always a fixed single call.
3. Multiple retrieval strategies are complementary, not assumed equivalent.
4. The system stops when evidence is sufficient or further retrieval has negligible marginal gain.
5. Every strategy choice is traceable to its current-data fit and historical observations.
6. The agent abstains when evidence remains insufficient.
7. No LLM, embeddings, network access, pandas, NumPy, or external vector database is required.
