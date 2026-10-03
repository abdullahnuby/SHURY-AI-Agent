# V15 CHANGELOG

## Agentic RAG
- Added deterministic `app/rag.py` indexing/retrieval/evidence engine.
- Added hybrid BM25 + character n-gram candidate generation and RRF fusion.
- Added lexical/heading reranking and MMR diversity selection.
- Added query decomposition, adaptive query expansion, evidence gating and fail-closed abstention.
- Added extractive source-bound citations and per-hop retrieval traces.
- Added incremental source indexing and access-aware memory decay reports.
- Added CSV/JSON/SQLite/Markdown/TXT ingestion with provenance metadata.
- Added RAG tools and CLI commands.
- Added V15 benchmark and regression suite.
