import json
import os
import sys
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
def outputs(environment):
    """Parse GITHUB_OUTPUT; later values win, as in the runner."""
    def read():
        if not environment.exists():
            return {}
        lines, values = environment.read_text(encoding="utf-8").split("\n"), {}
        while len(lines) > 1:
            name, delimiter = lines.pop(0).split("<<")
            end = lines.index(delimiter)
            values[name], lines = "\n".join(lines[:end]), lines[end + 1:]
        return values
    return read


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


FAKE_CLAUDE = """import json, os, sys
prompt = sys.stdin.read()
record = {"args": sys.argv[1:], "prompt": prompt, "env": sorted(k for k in os.environ if k.startswith("INPUT_")),
          "api_key": os.environ.get("ANTHROPIC_API_KEY"), "oauth": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")}
open(os.environ["FAKE_CLAUDE_RECORD"], "w", encoding="utf-8").write(json.dumps(record))
print(json.dumps(json.loads(os.environ["FAKE_CLAUDE_RESPONSE"])))
sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0")))
"""


@pytest.fixture
def fake_claude(monkeypatch, tmp_path):
    """Put a recording `claude` executable first on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "fake_claude.py").write_text(FAKE_CLAUDE, encoding="utf-8")
    if os.name == "nt":
        (bin_dir / "claude.cmd").write_text(f'@"{sys.executable}" "%~dp0fake_claude.py" %*\n', encoding="utf-8")
    else:
        launcher = bin_dir / "claude"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake_claude.py" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    record = tmp_path / "claude-record.json"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSE", json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "## Lunch\nRice\n"}))
    return lambda: json.loads(record.read_text(encoding="utf-8"))
