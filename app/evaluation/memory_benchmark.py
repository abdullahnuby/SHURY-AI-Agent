"""Small offline acceptance benchmark for the durable memory subsystem.

It mirrors the core concerns highlighted by recent memory evaluations: accurate
recall, dynamic state updates, episodic/workflow memory, temporal validity,
selective forgetting, provenance, and cross-session persistence.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from app.knowledge.memory import Memory


def run_memory_benchmark(path: str | Path | None = None) -> dict:
    owns_temp = path is None
    root = Path(tempfile.mkdtemp(prefix="agent-memory-bench-")) if owns_temp else None
    db = (root / "memory.db") if root else Path(path)
    m = Memory(db)
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = ""):
        checks.append((name, bool(ok), detail))

    m.set_fact("name", "Abdullah")
    check("static_fact_recall", m.get_fact("name") == "Abdullah")

    m.set_fact("project", "KEMEX")
    m.set_fact("project", "KEMEX Agent")
    check("dynamic_state_tracking", m.get_fact("project") == "KEMEX Agent")
    check("history_preserved", any(h["action"] == "SUPERSEDE" for h in m.memory_history(key="project")))

    m.add_episode("we decided to use a modular memory architecture", "completed", session_id="s1")
    check("episodic_recall", bool(m.search_memory("modular memory architecture", top_k=5)))

    m.working_put("s1", "current task: memory benchmark", priority=5)
    check("working_memory_scope", bool(m.working_recall("s1")) and not m.working_recall("s2"))

    m.remember("temporary state", kind="fact", key="temporary", expires_at="2000-01-01T00:00:00")
    check("temporal_expiry", m.get_fact("temporary") is None)

    m.remember("a reusable workflow", kind="procedural", key="benchmark workflow", metadata={"tool_sequence": ["calculator"]})
    check("procedural_lane", bool(m.procedural_memory("benchmark workflow")))

    mid = m.get_memory(m._q("SELECT id FROM memory_items WHERE key='name' AND status='active'")[0][0])
    check("provenance", bool(mid) and mid["source"] == "user")

    deleted = m.forget("project")
    check("selective_forgetting", deleted >= 1 and m.get_fact("project") is None)

    health = m.memory_health()
    check("health_report", health.get("ok") is True and "active_by_kind" in health)

    export = m.export_memory(include_history=True, include_episodes=True)
    check("portable_export", export.get("schema") == "personal-agent.memory.v1" and bool(export.get("items")))

    import_path = Path(tempfile.mkdtemp(prefix="agent-memory-restore-")) / "restore.db"
    restored = Memory(import_path)
    restore_result = restored.restore_memory(export, include_episodes=True)
    check("portable_restore", restore_result["imported_items"] >= 2 and restored.get_fact("name") == "Abdullah")

    passed = sum(1 for _, ok, _ in checks if ok)
    result = {"passed": passed, "total": len(checks), "score": round(passed / max(1, len(checks)), 3),
              "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks]}
    return result
