# Layer 4 — World Model

The world layer maintains an explicit representation of agent-relevant state, turns tool outputs into observations, records state diffs, predicts consequences before risky actions, persists a session-scoped world snapshot, and exposes a read-only simulation tool.

Design principles:

- State is explicit and typed; raw model text is never authoritative state.
- Tool contracts provide deterministic predictions; an optional model can enrich them.
- Observations are evidence with provenance, verification and confidence.
- Actual state changes are accepted only through governed runtime transitions or strict `world_delta` payloads from trusted tool adapters.
- Predictions are advisory unless the existing policy/approval layer blocks an action.
- Session world state is isolated by `session_id` and persisted in working memory.
