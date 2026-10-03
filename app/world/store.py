from __future__ import annotations

import json

from app.domain.world import WorldState

WORLD_KIND = "world_state"


def save_session_world(memory, session_id: str | None, world: WorldState) -> bool:
    if not session_id:
        return False
    payload = json.dumps(world.snapshot(), ensure_ascii=False, default=str)
    current = load_session_world(memory, session_id)
    fingerprint = world.fingerprint()
    if current.fingerprint() == fingerprint:
        return False
    memory.working_put(
        session_id,
        payload,
        kind=WORLD_KIND,
        priority=5,
        metadata={"fingerprint": fingerprint, "schema": "world-state.v1"},
    )
    return True


def load_session_world(memory, session_id: str | None) -> WorldState:
    if not session_id:
        return WorldState()
    rows = memory.working_recall(session_id, limit=20)
    for row in rows:
        if row.get("kind") != WORLD_KIND:
            continue
        try:
            payload = json.loads(row.get("content", "{}"))
            if isinstance(payload, dict):
                return WorldState.from_snapshot(payload)
        except Exception:
            continue
    return WorldState()
