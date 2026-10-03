# SHURY — PHASE 8: EPISODIC / EXPERIENCE MEMORY

## Contract

Episodic memory is the durable record of what happened in prior interactions and tasks. It is separate from factual/profile memory and from the LearningStore optimization substrate.

### Stored evidence

Each episode preserves, when available:

- user message
- assistant response
- tool events and their verified outcomes
- overall outcome/status
- timestamp
- owner/scope context
- session id
- run id
- extracted entities
- experience kind (`interaction` or `task`)
- provenance metadata

Sensitive credentials are recursively redacted before persistence.

## APIs

The canonical `Memory` authority exposes dedicated episodic methods:

- `record_episode`
- `get_episode`
- `retrieve_episodes`
- `retrieve_experience`
- `experience_timeline`

Legacy `add_episode` remains a compatibility wrapper.

## Retrieval boundary

`retrieve_episodes()` queries `memory_episodes` directly under owner/session/run scope and scores the episode evidence deterministically using lexical overlap, tool evidence, entities, phrase matching, and recency.

Factual retrieval remains available through the existing memory retrieval API, but experience-oriented context is now retrieved through the dedicated episodic path. `recall_context()` uses this dedicated episodic retrieval for the episodic portion of context.

## Canonical runtime capture

The canonical Brain runtime records the interaction as an episode after execution, including structured tool evidence and extracted entities. Early non-tool outcomes are also captured before returning.

The legacy runtime remains compatible and now stores the same structured experience fields.

## Separation from LearningStore

`LearningStore.experiences` is not used as the user-facing episodic memory authority. It remains the optimization/learning substrate. User history and prior-task recall are represented by `memory_episodes` under the canonical Memory authority.

## Migration

Phase 8 extends the existing `memory_episodes` table in place with:

- `tool_events`
- `entities`
- `experience_kind`

Existing rows remain valid and are assigned safe defaults during migration. No destructive replacement is performed.
