# Research Notes V15

Research checked on 2026-09-29.

## RAG / Agentic Retrieval

1. **Data Agents: Agentic Data Systems** (2026-09-21, arXiv:2609.24137) describes semantic data organization, agentic orchestration/optimization, feedback refinement, memory management and proactive adaptation as core components of data agents. The V15 interpretation is a deterministic separation between indexing, retrieval control, evidence verification, and memory decay.

2. **Reason Before You Retrieve: Agentic Planning for Multi-modal RAG** (2026-06-24, arXiv:2607.22643) explicitly models the information need and retrieval location before searching. V15 implements a smaller text/table analogue through query decomposition, retrieval routing signals, and source-aware evidence aggregation.

3. **SPARKLE: A Structured and Plug-and-play Agentic Retrieval Policy for Adaptive RAG Models** (ACL 2026) uses a separate proxy policy to control retrieval decisions. V15 uses a deterministic policy instead of RL: complexity-aware decomposition, evidence-gate thresholds, targeted retry, and query expansion.

4. **Reasoning with Memory: Adaptive Information Management for Retrieval-Augmented Generation** (ACL Findings 2026) introduces working-memory management for long multi-hop reasoning. V15 keeps an explicit indexed working-memory analogue and access-based decay while avoiding learned memory extraction.

5. **AgenticRAGTracer** (ACL Findings 2026; arXiv:2602.19127; GitHub: YqjMartin/AgenticRAGTracer) argues for hop-level diagnosis because final-answer metrics hide where multi-step retrieval fails. V15 records per-hop queries, retrieval counts and evidence coverage.

6. **RAG over Tables: Hierarchical Memory Index, Multi-Stage Retrieval, and Benchmarking** (ACL Findings 2026) motivates hierarchical table-aware indexing. V15 indexes schema metadata plus row-level evidence and keeps source/table paths in provenance.

7. **Page-Aware Retrieval-Augmented Generation for EvalLLM 2026** (2026-09-28, arXiv:2609.34776) reports that page selection can be more important than semantic retrieval alone on PDF QA. V15 therefore preserves source/section/row metadata so later PDF/page adapters can reuse the same evidence contract.

8. **Adaptive Agentic RAG** (GitHub: mmnsrti/adaptive-agentic-rag) demonstrates the practical combination of hybrid retrieval, reranking, evidence gating, adaptive recovery, citation binding and safe abstention. V15 adopts the control-flow principles but replaces dense embeddings/cross-encoders/NLI with deterministic sparse/character scoring.

9. **DataSpace** (arXiv:2608.03451; GitHub: HKUSTDial/DataSpace) evaluates heterogeneous workspaces and deterministic complete-result verification across CSV, JSON, SQLite, Markdown, PDF and video. V15 reuses the same reliability principle: evidence discovery and provenance are first-class rather than hidden inside generation.

## Algorithm decisions

- **BM25-style retrieval** remains the primary sparse relevance signal.
- **Character 3-gram cosine** is a secondary lexical robustness signal, not semantic embedding.
- **RRF** is used to fuse independently ranked evidence lists without calibrating scores across retrieval methods.
- **MMR** reduces redundant evidence and improves source/chunk diversity.
- **Query decomposition + query expansion** provide deterministic multi-hop recovery.
- **Evidence gate** prevents unsupported generation and creates an explicit abstention path.
- **Extractive synthesis** makes every returned sentence traceable to a chunk.

## GitHub references reviewed

- HKUSTDial/DataSpace — heterogeneous, verifiable data-agent benchmark and runtime.
- YqjMartin/AgenticRAGTracer — hop-aware agentic RAG evaluation.
- mmnsrti/adaptive-agentic-rag — hybrid/RRF/reranking/evidence gate reference architecture.
- InternScience/MLEvolve — adaptive search and experience-driven optimization patterns carried forward from earlier agent work.

## Deliberately not copied

- Dense embedding models and vector databases: would violate the project's model-free/standard-library boundary.
- LLM query rewriting and NLI judges: replaced by deterministic decomposition, lexical expansion, citation binding and conservative evidence thresholds.
- RL-based retrieval policies: replaced by transparent rule-based control so behavior remains reproducible and auditable.
