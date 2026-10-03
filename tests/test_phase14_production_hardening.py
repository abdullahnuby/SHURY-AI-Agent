from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from app.knowledge.memory import Memory, configure
from app.production.config import ProductionConfig
from app.production.rate_limit import RateLimiter
from app.production.redaction import fingerprint, redact, safe_request_id


def test_rate_limiter_refills_without_global_sleep():
    now = [0.0]
    limiter = RateLimiter(capacity=2, refill_per_second=1.0, clock=lambda: now[0])
    assert limiter.allow("a").allowed
    assert limiter.allow("a").allowed
    denied = limiter.allow("a")
    assert not denied.allowed and 0 < denied.retry_after <= 1.0
    now[0] = 1.0
    assert limiter.allow("a").allowed


def test_redaction_is_recursive_and_fingerprints_are_stable():
    payload = {"Authorization": "Bearer abc", "nested": {"api_key": "secret", "ok": "x"}, "path": "C:\\Users\\Abdullah\\secret.txt"}
    safe = redact(payload)
    assert safe["Authorization"] == "<redacted>"
    assert safe["nested"]["api_key"] == "<redacted>"
    assert safe["path"] == "<path>"
    assert fingerprint(payload) == fingerprint(dict(payload))
    assert fingerprint({"token": "a"}) != fingerprint({"token": "b"})
    assert 8 <= len(safe_request_id(None)) <= 64


def test_production_config_requires_auth_token_when_enabled(monkeypatch):
    monkeypatch.setenv("SHURY_ENV", "production")
    monkeypatch.delenv("SHURY_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        ProductionConfig.from_env()
    monkeypatch.setenv("SHURY_API_TOKEN", "unit-test-secret")
    cfg = ProductionConfig.from_env()
    assert cfg.require_auth and cfg.api_token == "unit-test-secret"


def test_api_tasks_persist_across_store_instances(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    task_id = "task-persistent-1"
    mem.create_api_task(task_id=task_id, message="hello", session_id="s1")
    mem.update_api_task(task_id, status="running", started_at=time.time())
    other = Memory(tmp_path / "memory.db")
    row = other.get_api_task(task_id)
    assert row and row["status"] == "running" and row["session_id"] == "s1"


def test_idempotency_is_atomic_and_conflicts_on_different_payload(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    response = {"task_id": "t1", "session_id": "s1"}
    status1, rec1 = mem.create_idempotent_api_task(
        route="/api/chat", idempotency_key="k1", request_hash="h1", task_id="t1",
        message="hello", session_id="s1", response=response,
    )
    status2, rec2 = mem.create_idempotent_api_task(
        route="/api/chat", idempotency_key="k1", request_hash="h1", task_id="t2",
        message="hello", session_id="s1", response={"task_id": "t2", "session_id": "s1"},
    )
    status3, rec3 = mem.create_idempotent_api_task(
        route="/api/chat", idempotency_key="k1", request_hash="h2", task_id="t3",
        message="different", session_id="s1", response={"task_id": "t3", "session_id": "s1"},
    )
    assert status1 == "new" and rec1["task_id"] == "t1"
    assert status2 == "replay" and rec2["task_id"] == "t1"
    assert status3 == "conflict" and rec3["task_id"] == "t1"
    assert mem.get_api_task("t2") is None and mem.get_api_task("t3") is None


def test_approval_state_is_durable_and_args_are_redacted(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    mem.claim_api_approval(task_id="t1", tool="save_note", args={"token": "secret", "text": "safe"}, expires_at=time.time() + 60)
    row = mem.get_api_approval("t1")
    assert row and row["args"]["token"] == "<redacted>"
    assert mem.set_api_approval("t1", True)
    assert mem.get_api_approval("t1")["decision"] is True
    assert not mem.set_api_approval("t1", False)


def _http_request(url: str, *, method="GET", body=None, headers=None):
    raw = None
    if body is not None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=raw, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        data = json.loads(exc.read().decode("utf-8"))
        return exc.code, data, dict(exc.headers)


def test_http_idempotency_and_security_headers(tmp_path, monkeypatch):
    import app.interfaces.web.server as server

    configure(tmp_path / "memory.db")
    server.PRODUCTION = ProductionConfig(environment="test", require_auth=False)
    server.RATE_LIMITER = RateLimiter(capacity=100, refill_per_second=100)
    calls = []

    def fake_run_task(task_id, message, session_id):
        calls.append((task_id, message, session_id))
        server.TASKS.update(task_id, status="completed", state={"final_message": "ok"}, error=None)

    monkeypatch.setattr(server, "_run_task", fake_run_task)
    srv = server.create_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        status, health, headers = _http_request(base + "/api/health")
        assert status == 200 and health["ok"] is True and headers.get("X-Content-Type-Options") == "nosniff"

        request_headers = {"Content-Type": "application/json", "Idempotency-Key": "same-123", "X-Request-ID": "req-1"}
        status1, body1, headers1 = _http_request(base + "/api/chat", method="POST", body={"message": "hello", "session_id": "s1"}, headers=request_headers)
        status2, body2, headers2 = _http_request(base + "/api/chat", method="POST", body={"message": "hello", "session_id": "s1"}, headers=request_headers)
        status3, body3, _ = _http_request(base + "/api/chat", method="POST", body={"message": "different", "session_id": "s1"}, headers=request_headers)
        assert status1 == 202 and status2 == 202 and body1["task_id"] == body2["task_id"]
        assert body2["idempotent_replay"] is True and status3 == 409
        assert len(calls) == 1
        assert headers1.get("X-Request-ID") == "req-1" and headers2.get("X-Request-ID") == "req-1"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


def test_http_production_auth_blocks_api_but_health_survives(tmp_path):
    import app.interfaces.web.server as server

    configure(tmp_path / "memory.db")
    original = server.PRODUCTION
    try:
        server.PRODUCTION = ProductionConfig(environment="production", require_auth=True, api_token="top-secret")
        status, _, _ = _http_request_from_server(server, "/api/health")
        assert status == 200
        status, payload, _ = _http_request_from_server(server, "/api/identity")
        assert status == 401 and payload["error"] == "authentication required"
        status, _, _ = _http_request_from_server(server, "/api/identity", headers={"Authorization": "Bearer top-secret"})
        assert status == 200
    finally:
        server.PRODUCTION = original


def _http_request_from_server(server, path, headers=None):
    srv = server.create_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        return _http_request(f"http://127.0.0.1:{srv.server_address[1]}{path}", headers=headers or {})
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


def test_task_lease_is_exclusive_and_expiration_blocks_stale_worker(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    mem.create_api_task(task_id="lease-1", message="hello", session_id="s1")
    assert mem.claim_api_task_lease("lease-1", "owner-a", 10)
    assert not mem.claim_api_task_lease("lease-1", "owner-b", 10)
    assert mem.api_task_execution_active("lease-1", "owner-a")
    assert not mem.api_task_execution_active("lease-1", "owner-b")
    mem.update_api_task("lease-1", status="timeout", lease_owner=None, lease_expires_at=0.0)
    assert not mem.api_task_execution_active("lease-1", "owner-a")
    assert not mem.renew_api_task_lease("lease-1", "owner-a", 10)


def test_task_schema_migrates_existing_database(tmp_path):
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE api_tasks (
        task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL,
        created_at REAL NOT NULL, started_at REAL, updated_at REAL NOT NULL, heartbeat_at REAL NOT NULL,
        progress_at REAL NOT NULL, state TEXT, error TEXT, revision INTEGER NOT NULL DEFAULT 1
    )""")
    conn.commit()
    conn.close()
    mem = Memory(db)
    columns = {row[1] for row in sqlite3.connect(db).execute("PRAGMA table_info(api_tasks)")}
    assert {"lease_owner", "lease_expires_at"}.issubset(columns)
    mem.create_api_task(task_id="migrated-1", message="ok", session_id="s1")
    assert mem.get_api_task("migrated-1")["lease_owner"] is None
