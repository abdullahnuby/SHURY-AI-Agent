import os
import time

from app.interfaces.web import server


def test_deterministic_chat_is_default_even_when_brain_is_configured(monkeypatch):
    monkeypatch.delenv("SHURY_ENABLE_COGNITIVE_UI", raising=False)
    assert server._use_cognitive() is False


def test_cognitive_chat_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("SHURY_ENABLE_COGNITIVE_UI", "1")
    assert server._use_cognitive() is True


def test_task_store_stale_releases_ui_without_losing_task_record(monkeypatch):
    monkeypatch.setattr(server, "TASK_STALE_SECONDS", 0.01)
    store = server.TaskStore()
    task_id = store.create("test", "session")
    store.update(task_id, status="running")
    time.sleep(0.03)
    stale = store.stale_task(store.get(task_id))
    assert stale["status"] == "timeout"
    assert stale["task_id"] == task_id
    assert "تحرير واجهة المحادثة" in stale["error"]
