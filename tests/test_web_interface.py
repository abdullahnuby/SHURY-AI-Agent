import json
import threading
import urllib.request

from app.interfaces.web.server import create_server, identity_payload


def _serve():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=3) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post(base, path, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base + path, data=data, method="POST", headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_identity_payload_has_shury():
    payload = identity_payload()
    assert payload["name"] == "SHURY"
    assert payload["short_name"] == "شوري"


def test_response_write_ignores_disconnected_client():
    from http import HTTPStatus

    from app.interfaces.web.server import Handler

    class DisconnectedWriter:
        def write(self, body):
            raise ConnectionAbortedError("client disconnected")

    class FakeHandler:
        wfile = DisconnectedWriter()

        def send_response(self, status):
            pass

        def send_header(self, name, value):
            pass

        def end_headers(self):
            pass

    Handler._send(FakeHandler(), HTTPStatus.OK, b"{}")


def test_web_health_and_identity_endpoints():
    server, thread = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, health = _get(base, "/api/health")
        assert status == 200
        assert health["ok"] is True
        assert health["brain"]["structured_goal"] is True
        assert health["brain"]["semantic_nlp"] == "arabic-retrieval-v1.0"
        status, identity = _get(base, "/api/identity")
        assert status == 200
        assert identity["name"] == "SHURY"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_homepage_exists():
    server, thread = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/", timeout=3) as response:
            body = response.read().decode("utf-8")
        assert "SHURY" in body
        assert "Talk to your agent" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_structured_goal_accepts_retrieval_native_request():
    server, thread = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, payload = _post(base, "/goal", {
            "goal": "calculate",
            "target": "2+2",
            "parameters": {"expression": "2+2"},
            "language": "en",
            "session_id": "structured-web-test",
        })
        assert status == 202
        assert payload["mode"] == "structured"
        assert payload["semantic_model"] == "arabic-retrieval-v1.0"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
