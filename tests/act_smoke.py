"""Exercise the actual composite through act; publishes only to a local mock server.

Run: python tests/act_smoke.py --act /path/to/act
On native Linux, also pass --runner-host host.docker.internal and configure its
Docker host mapping if needed. Docker Desktop resolves that hostname by default.
"""
import argparse
import json
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--act", default="act")
    parser.add_argument("--runner-host", default="host.docker.internal")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    posts = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.end_headers()
            self.wfile.write(b'<rss version="2.0"><channel><title>Smoke</title><link>https://example.com</link><description>Fixture</description><item><title>Fixture article</title><description>Fixture summary</description></item></channel></rss>')

        def do_POST(self):
            posts.append((self.path, self.headers["Authorization"], self.headers["X-Content-Format"],
                          json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"smoke-note"}')

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="notomate-act-") as tmp:
            event = Path(tmp) / "event.json"
            event.write_text(json.dumps({"event": "workflow_dispatch", "workspace": {"id": "mock-workspace", "name": "Mock"}}))
            result = subprocess.run([
                args.act, "workflow_dispatch", "--directory", str(root),
                "--workflows", str(root / "tests/act-smoke.yml"), "--eventpath", str(event),
                "--bind", "--pull=false", "--action-offline-mode",
                "--platform", "ubuntu-latest=catthehacker/ubuntu:act-latest",
                "--env", f"MOCK_ORIGIN=http://{args.runner_host}:{server.server_port}",
            ], cwd=root)
            if result.returncode:
                raise SystemExit(result.returncode)
        assert len(posts) == 1, f"Expected exactly one note, got {len(posts)}"
        path, auth, content_format, body = posts[0]
        assert path == "/api/v1/workspaces/mock-workspace/notes"
        assert auth == "Bearer mock-only-key" and content_format == "markdown"
        assert body["visibility"] == "private" and "Fixture article" in body["content"]
        print("act composite smoke passed: exactly one Markdown note and correct action outputs.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
