# SHURY V22.15.0 — Answer & Reasoning Core

Base: V22.14.1

## Purpose
Add a deterministic answer-policy layer for factual questions without using an LLM.

## Architecture
- Generic factual questions become the `knowledge_query` semantic capability only when no stronger known intent owns the turn.
- `question_answering` executes a bounded source policy: local RAG → web when needed/fresh → RAG re-grounding → extractive fallback → explicit abstention.
- Responses expose provenance and no longer leak runtime/tool envelopes.
- No model provider, embedding service, or remote summarizer is required by this path.

## Validation
- Focused regression suite: 34 passed
- compileall: OK
- web import + tool registry: OK
- Full repository pytest run: reached 73% with no reported failures before the 5-minute execution gate expired; full-run completion remains an acceptance item because the existing suite contains long-running/stateful tests.
