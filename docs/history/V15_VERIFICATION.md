# V15 Verification

Verification target: Personal Agent V15.

- Version: 15.0.0
- Python standard library only
- No LLM / embeddings / network calls / pandas / NumPy / external vector DB
- Regression suite includes V4-V15 tests
- V15 benchmark includes indexing, incremental skip, grounded retrieval, repeatability, fail-closed abstention, and memory decay observability

The release should only be packaged after `python -m pytest -q`, `python -m compileall -q app tests`, and `python -m app.v15_benchmark` (or module equivalent) are green.


Release verification results:
- Full regression: 121/121 passed
- V15 benchmark: 6/6 passed
- compileall: passed
- Agent routing: `rag ...` plans to `rag_query`
- Cache safety: verified cached plan structure is reused with execution state reset to pending
