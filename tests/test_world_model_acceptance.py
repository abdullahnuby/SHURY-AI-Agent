from __future__ import annotations

import app.knowledge.memory as memory_mod
from app.runtime.cognitive_agent import run_cognitive
from app.world.store import load_session_world


def _setup(tmp_path, monkeypatch):
    memory_mod.configure(tmp_path / "memory.db")
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("AGENT_WORKSPACE", str(ws))
    monkeypatch.setenv("SHURY_NLP_MODE", "off")
    return ws


def test_real_user_world_state_survives_next_turn(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = run_cognitive("calculate 2+2", approve=lambda *a, **k: True, max_steps=2, session_id="u1")
    assert s.status == "completed"
    world = load_session_world(memory_mod.get_memory(), "u1")
    assert world.last_outputs.get("last_result") == 4
    assert world.observations
