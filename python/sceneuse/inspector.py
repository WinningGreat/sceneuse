"""Local inspector: scene graph + damage, not a screenshot viewer."""

from __future__ import annotations

import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .client import Client, SceneuseError

HOST = os.environ.get("SCENEUSE_INSPECTOR_HOST", "127.0.0.1")
PORT = int(os.environ.get("SCENEUSE_INSPECTOR_PORT", "8765"))


def static_dir() -> Path:
    env = os.environ.get("SCENEUSE_INSPECTOR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    repo = here.parents[2] / "inspector"
    if (repo / "index.html").exists():
        return repo
    bundled = here.parent / "static"
    return bundled


class Hub:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.scene: dict | None = None
        self.error: str | None = None
        self.connected = False
        self._stop = threading.Event()

    def run(self) -> None:
        delay = 0.4
        while not self._stop.is_set():
            try:
                client = Client()
                client.connect()
                client.subscribe(tiles=True)
                with self.lock:
                    self.connected = True
                    self.error = None
                delay = 0.4
                for scene in client.scenes():
                    if self._stop.is_set():
                        break
                    raw = dict(scene.raw)
                    with self.lock:
                        self.scene = raw
                        self.connected = True
                        self.error = None
            except (OSError, ConnectionError, SceneuseError) as e:
                with self.lock:
                    self.connected = False
                    self.error = str(e)
                self._stop.wait(delay)
                delay = min(delay * 1.5, 3.0)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "connected": self.connected,
                "error": self.error,
                "scene": self.scene,
            }


HUB = Hub()
_actor: Client | None = None
_actor_lock = threading.Lock()


def actor() -> Client:
    global _actor
    with _actor_lock:
        if _actor is None:
            _actor = Client()
            _actor.connect()
        return _actor


def serve() -> None:
    root = static_dir()
    thread = threading.Thread(target=HUB.run, name="sceneuse-hub", daemon=True)
    thread.start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            pass

        def _json(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/scene":
                self._json(200, HUB.snapshot())
                return
            rel = "index.html" if path == "/" else path.lstrip("/")
            file = (root / rel).resolve()
            try:
                file.relative_to(root.resolve())
            except ValueError:
                self.send_error(403)
                return
            if not file.is_file():
                self.send_error(404)
                return
            data = file.read_bytes()
            mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                params = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                self._json(400, {"error": {"code": "bad_request", "message": "invalid JSON"}})
                return
            if path == "/api/act":
                try:
                    result = actor().act(**params)
                    self._json(200, {"ok": True, "result": result})
                except SceneuseError as e:
                    self._json(400, {"error": {"code": e.code, "message": e.message}})
                except OSError as e:
                    self._json(503, {"error": {"code": "internal", "message": str(e)}})
                return
            self.send_error(404)

    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"sceneuse inspector  http://{HOST}:{PORT}", flush=True)
    print(f"static files        {root}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping inspector")


if __name__ == "__main__":
    serve()
