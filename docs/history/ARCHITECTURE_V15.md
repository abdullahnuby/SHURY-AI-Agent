# Personal Agent V15 — Deterministic Agentic RAG

V15 adds a model-free RAG subsystem to the V14 heterogeneous evidence engine. The runtime stays provider-independent: no LLM, embeddings API, network calls, pandas, NumPy, or external vector database are required.

## 1. Research-derived design

Current 2026 RAG work increasingly emphasizes adaptive retrieval, query decomposition, explicit working memory, multi-hop process diagnostics, hybrid retrieval/reranking, source attribution, and fail-closed evidence gating. V15 translates those architectural ideas into deterministic algorithms.

## 2. Ingestion

Supported local sources:
- TXT / Markdown: heading-aware hierarchical chunks with bounded overlap.
- CSV: schema chunk plus row-level chunks.
- JSON: scalar/path-aware chunks for nested dictionaries/lists.
- SQLite/DB: table-schema chunks plus row-level chunks.

Every source and chunk receives a SHA-256 fingerprint. Indexing is incremental: unchanged files are skipped.

## 3. Retrieval

The retrieval portfolio is:

```text
query
  ├─ BM25-style sparse retrieval
  ├─ character 3-gram cosine similarity
  └─ Reciprocal Rank Fusion (RRF)
            ↓
      lexical + structural reranking
            ↓
        MMR diversity
```

Character n-gram retrieval is intentionally called a lexical secondary signal rather than a semantic embedding. It improves robustness to morphology, punctuation, and small spelling differences without pretending to understand unseen semantics.

## 4. Agentic control flow

```text
Query
 ↓
Query decomposition
 ↓
Initial hybrid retrieval
 ↓
Evidence gate
 ├─ sufficient → extractive answer + citations
 └─ insufficient → targeted retry / query expansion
                         ↓
                      stop/abstain
```

Complex conjunctive queries are decomposed into subqueries. The runtime merges unique evidence across hops and stops early when coverage is sufficient. Otherwise it fails closed rather than fabricating a response.

## 5. Grounded answer

The generation substitute is extractive synthesis. Selected sentences are returned with citation bindings such as `[S1]`; each citation maps to an exact retrieved chunk, source, and score.

This is deliberately different from LLM RAG: the runtime cannot invent unsupported prose because it only emits sentences present in retrieved evidence.

## 6. Memory

Agent notes/facts can be copied into the RAG index with `/rag-memory-index`. Chunk access is tracked separately from retrieval ranking. A retention report estimates exponential decay from last access and retrieval frequency. Dynamic access signals are not injected into within-query ranking, preserving repeatability.

## 7. Verification

Every RAG result records:
- query and decomposition
- hop trace
- evidence coverage
- source diversity
- selected retrieval records
- method identifiers
- grounded/abstained state

The query log enables later audit and benchmark replay.

## 8. Language boundary

The model-free runtime is language-preserving: Arabic queries retrieve Arabic evidence and English queries retrieve English evidence after deterministic normalization. Cross-language semantic retrieval would require an additional semantic model or translation layer and is intentionally not claimed by V15.
