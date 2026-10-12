# Phase 9 — Knowledge Base Separation

## Contract

SHURY keeps personal/episodic memory separate from world/project knowledge.

- Personal memory is owned by the user/session/run memory authority.
- Knowledge is stored in the local RAG corpus as world or project evidence.
- Knowledge sources carry a stable `source_ref`, `origin`, and `source_kind` provenance record.
- Project knowledge carries `project_id`; world knowledge is shared across projects.
- Project retrieval includes world knowledge plus the requested project only.
- Personal memory is never copied into `.rag_memory` or the RAG corpus.
- The legacy `index_agent_memory` operation remains as a compatibility gate and returns a blocked result.
- Knowledge can be added, listed, queried, and removed through `KnowledgeBase` without editing Python source.

## Public Boundary

`app.knowledge.knowledge_base.KnowledgeBase` is the source-managed knowledge facade.

`RAGEngine.index_knowledge`, `index_knowledge_text`, `list_knowledge`, `remove_knowledge`, and `knowledge_stats`
implement the same boundary at the storage layer.

## Provenance

Each RAG source has:

- `knowledge_scope`
- `project_id`
- `source_ref`
- `provenance_json`
- `content_hash`

Existing sources are backfilled with deterministic provenance during schema initialization.

## Retrieval Boundary

RAG retrieval accepts an optional `project_id` and filters candidates before scoring:

`world` OR `project == requested project`.

Adaptive RAG propagates that project filter through all strategies and preserves the source provenance metadata in retrieval results.

## Non-goals

Phase 9 does not modify personal-memory extraction, promotion, temporal correction, entity/relation semantics, or Brain planning logic.
