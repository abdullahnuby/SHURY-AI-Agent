# Agent V6 — Deterministic Cognitive Runtime

## Added
- Explicit Goal Model with deterministic compound-goal decomposition.
- Operator abstraction derived from the Tool Registry.
- Deterministic replanning assessment after failed observations.
- Tool outcome telemetry and empirical reliability stored in SQLite.
- Append-only event ledger for tool observations.
- Forward-reference handling so compound pipelines do not require prior conversational memory.
- V6 regression suite.

## Verification
- 37 tests passed.
- Compound goal verified end-to-end: calculator -> save_note.
- No LLM/API dependency added.
