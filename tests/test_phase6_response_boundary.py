from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from types import SimpleNamespace

import app.interfaces.web.server as web
from app.interfaces.cli import show_result


def _server():
    server = web.create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _get(base: str, path: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(base + path, headers=headers or {})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_public_state_contains_only_user_facing_fields():
    state = SimpleNamespace(
        status="completed",
        response="The result is 400.",
        run_id="private-run-id",
        trace_id="private-trace-id",
    )
    public = web.serialize_public_state(state)
    assert public == {"status": "completed", "final_message": "The result is 400."}
    assert "run_id" not in public
    assert "trace_id" not in public
    assert "cognitive" not in public
    assert "plan" not in public


def test_public_task_projection_strips_internal_cognitive_state():
    task = {
        "task_id": "task-visible-to-client",
        "session_id": "session-visible-to-client",
        "status": "completed",
        "state": {
            "run_id": "private-run",
            "trace_id": "private-trace",
            "status": "completed",
            "final_message": "تم التنفيذ بنجاح.",
            "plan": [{"tool": "calculator"}],
            "cognitive": {"trace": [{"kind": "decision"}], "decision": {"rationale": "private"}},
            "world": {"private": True},
        },
        "error": None,
    }
    public = web.serialize_task_for_api(task)
    assert public["state"] == {"status": "completed", "final_message": "تم التنفيذ بنجاح."}
    assert "run_id" not in public
    assert "trace_id" not in public
    assert "plan" not in public
    assert "cognitive" not in public
    assert "debug" not in public


def test_debug_projection_is_explicitly_opt_in(monkeypatch):
    route = SimpleNamespace(query="debug=1")
    monkeypatch.setenv("SHURY_ENABLE_DEBUG_UI", "0")
    assert web._debug_ui_requested(route) is False
    monkeypatch.setenv("SHURY_ENABLE_DEBUG_UI", "1")
    assert web._debug_ui_requested(route) is True


def test_web_task_endpoint_hides_internal_state_by_default(monkeypatch):
    task = {
        "task_id": "task-123",
        "session_id": "session-123",
        "status": "completed",
        "state": {
            "run_id": "private-run",
            "trace_id": "private-trace",
            "status": "completed",
            "final_message": "The result is 400.",
            "plan": [{"tool": "calculator"}],
            "cognitive": {"trace": [{"kind": "decision"}]},
        },
        "error": None,
    }
    monkeypatch.setattr(web.TASKS, "get", lambda _task_id: dict(task))
    monkeypatch.setattr(web.TASKS, "stale_task", lambda current: current)
    server, thread = _server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, payload = _get(base, "/api/tasks?id=task-123")
        assert status == 200
        encoded = json.dumps(payload, ensure_ascii=False)
        assert payload["state"]["final_message"] == "The result is 400."
        assert "private-run" not in encoded
        assert "private-trace" not in encoded
        assert '"cognitive"' not in encoded
        assert '"plan"' not in encoded
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_task_endpoint_debug_projection_requires_both_switches(monkeypatch):
    task = {
        "task_id": "task-123",
        "session_id": "session-123",
        "status": "completed",
        "state": {
            "run_id": "private-run",
            "status": "completed",
            "final_message": "The result is 400.",
            "cognitive": {"trace": [{"kind": "decision"}]},
        },
        "error": None,
    }
    monkeypatch.setattr(web.TASKS, "get", lambda _task_id: dict(task))
    monkeypatch.setattr(web.TASKS, "stale_task", lambda current: current)
    monkeypatch.setenv("SHURY_ENABLE_DEBUG_UI", "1")
    server, thread = _server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, payload = _get(base, "/api/tasks?id=task-123&debug=1")
        assert status == 200
        assert payload["state"]["final_message"] == "The result is 400."
        assert payload["debug"]["run_id"] == "private-run"
        assert payload["debug"]["cognitive"]["trace"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_cli_normal_mode_prints_only_response(capsys):
    state = SimpleNamespace(
        response="The result is 400.",
        final_message="private fallback",
        run_id="private-run-id",
        trace_id="private-trace-id",
    )
    show_result(state, debug=False)
    out = capsys.readouterr().out
    assert out.strip() == "The result is 400."
    assert "private-run-id" not in out
    assert "private-trace-id" not in out
