import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.fixture
def environment(monkeypatch, tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"event": "schedule", "workspace": {"id": "workspace-1", "name": "Test"}}), encoding="utf-8")
    output = tmp_path / "outputs.txt"
    for key, value in {
        "GITHUB_EVENT_PATH": str(event), "GITHUB_OUTPUT": str(output),
        "INPUT_NOTOMATE_BASE_URL": "http://notomate.test", "INPUT_NOTOMATE_API_KEY": "test-secret",
        "INPUT_NOTE_VISIBILITY": "private", "INPUT_TIMEZONE": "Asia/Taipei",
    }.items():
        monkeypatch.setenv(key, value)
    return output


@pytest.fixture
def server():
    state = {"posts": [], "status": 201, "body": {"id": "note-123"}, "feed": b""}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.end_headers()
            self.wfile.write(state["feed"])

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["posts"].append((self.path, dict(self.headers), body))
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(state["body"]).encode())

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{httpd.server_port}"
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
