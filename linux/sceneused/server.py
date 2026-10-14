"""NDJSON Unix-socket server for Linux sceneused."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from typing import Any

from . import __version__
from .atspi_snap import Snap, accessibility_ok, do_invoke, do_set, now_ms, snapshot

PROTOCOL = 1
ADAPTER = "linux"


class Connection:
    def __init__(self, sock: socket.socket, path_id: str):
        self.sock = sock
        self.id = path_id
        self.buf = b""
        self.subscribed = False
        self.tiles = True
        self.lock = threading.Lock()

    def send(self, obj: dict[str, Any]) -> None:
        data = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
        with self.lock:
            self.sock.sendall(data)


class Server:
    def __init__(self, path: str):
        self.path = path
        self._sock: socket.socket | None = None
        self._conns: dict[str, Connection] = {}
        self._lock = threading.Lock()
        self._seq = 0
        self._last: Snap = Snap()
        self._observe_window: str | None = None
        self._observe_app: str | None = None
        self._stop = threading.Event()

    def serve_forever(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        if os.path.exists(self.path):
            os.unlink(self.path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.path)
        os.chmod(self.path, 0o666)
        srv.listen(16)
        srv.settimeout(0.5)
        self._sock = srv
        print(f"sceneused linux on {self.path}", flush=True)

        emitter = threading.Thread(target=self._emit_loop, daemon=True)
        emitter.start()

        try:
            while not self._stop.is_set():
                try:
                    conn_sock, _ = srv.accept()
                except socket.timeout:
                    continue
                cid = str(uuid.uuid4())
                conn = Connection(conn_sock, cid)
                with self._lock:
                    self._conns[cid] = conn
                threading.Thread(target=self._client_loop, args=(conn,), daemon=True).start()
        finally:
            srv.close()
            if os.path.exists(self.path):
                os.unlink(self.path)

    def stop(self) -> None:
        self._stop.set()

    def _client_loop(self, conn: Connection) -> None:
        conn.sock.settimeout(1.0)
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                conn.buf += chunk
                while b"\n" in conn.buf:
                    line, conn.buf = conn.buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    self._handle(conn, line)
        except OSError:
            pass
        finally:
            with self._lock:
                self._conns.pop(conn.id, None)
            try:
                conn.sock.close()
            except OSError:
                pass

    def _fail(self, conn: Connection, mid: str | None, code: str, message: str) -> None:
        msg: dict[str, Any] = {"v": PROTOCOL, "type": "error", "error": {"code": code, "message": message}}
        if mid:
            msg["id"] = mid
        conn.send(msg)

    def _ok(self, conn: Connection, mid: str, result: dict[str, Any]) -> None:
        conn.send({"v": PROTOCOL, "type": "ok", "id": mid, "result": result})

    def _handle(self, conn: Connection, line: bytes) -> None:
        try:
            obj = json.loads(line.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._fail(conn, None, "bad_request", "invalid JSON")
            return
        typ = obj.get("type")
        mid = obj.get("id")
        params = obj.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if typ == "hello":
            if not mid:
                return self._fail(conn, None, "bad_request", "id required")
            return self._ok(
                conn,
                mid,
                {"protocol": PROTOCOL, "adapter": ADAPTER, "version": __version__},
            )
        if typ == "status":
            if not mid:
                return self._fail(conn, None, "bad_request", "id required")
            a11y = accessibility_ok()
            return self._ok(
                conn,
                mid,
                {
                    "permissions": {
                        "screen_recording": False,
                        "accessibility": a11y,
                    },
                    "socket": self.path,
                    "adapter": ADAPTER,
                    "version": __version__,
                    **({"tcc_hint": "AT-SPI bus unavailable — run at-spi-bus-launcher"} if not a11y else {}),
                },
            )
        if typ == "subscribe":
            if not mid:
                return self._fail(conn, None, "bad_request", "id required")
            conn.tiles = bool(params.get("tiles", True))
            conn.subscribed = True
            if params.get("window"):
                self._observe_window = str(params["window"])
            if params.get("app"):
                self._observe_app = str(params["app"])
            self._push_scene(force=True)
            return self._ok(conn, mid, {"subscribed": True})
        if typ == "unsubscribe":
            if not mid:
                return self._fail(conn, None, "bad_request", "id required")
            conn.subscribed = False
            return self._ok(conn, mid, {"subscribed": False})
        if typ == "target":
            if not mid:
                return self._fail(conn, None, "bad_request", "id required")
            window = params.get("window")
            app = params.get("app")
            if not window and not app:
                self._observe_window = None
                self._observe_app = None
                self._push_scene(force=True)
                return self._ok(conn, mid, {"cleared": True})
            self._observe_window = str(window) if window else None
            self._observe_app = str(app) if app else None
            snap = self._refresh()
            obs = snap.observe or snap.focus
            if not obs:
                return self._fail(conn, mid, "not_found", "no matching window/app")
            return self._ok(
                conn,
                mid,
                {
                    "window": obs.get("window"),
                    "app": obs.get("app"),
                    "pid": obs.get("pid"),
                },
            )
        if typ == "act":
            if not mid:
                return self._fail(conn, None, "bad_request", "id required")
            try:
                self._act(params)
            except KeyError as e:
                return self._fail(conn, mid, "not_found", str(e))
            except ValueError as e:
                return self._fail(conn, mid, "bad_request", str(e))
            except PermissionError as e:
                return self._fail(conn, mid, "permission_denied", str(e))
            except Exception as e:  # noqa: BLE001
                return self._fail(conn, mid, "internal", str(e))
            self._settle()
            self._push_scene(force=True)
            return self._ok(conn, mid, {"ok": True})

        self._fail(conn, mid, "unknown_type", f"unknown type {typ}")

    def _act(self, params: dict[str, Any]) -> None:
        op = params.get("op") or ""
        if op == "invoke":
            node = params.get("node")
            if not node:
                raise ValueError("node required")
            acc = self._last.node_refs.get(str(node))
            if acc is None:
                raise KeyError(f"unknown node {node}")
            do_invoke(acc, params.get("action"))
            return
        if op == "set":
            node = params.get("node")
            if not node:
                raise ValueError("node required")
            if "value" not in params:
                raise ValueError("value required")
            acc = self._last.node_refs.get(str(node))
            if acc is None:
                raise KeyError(f"unknown node {node}")
            do_set(acc, str(params["value"]))
            return
        if op == "raise":
            # Best-effort: no foreign-toplevel in Xvfb sandbox.
            return
        if op in {"hit", "key", "scroll", "drag"}:
            raise PermissionError(f"{op} needs uinput/RemoteDesktop (not in AT-SPI sandbox)")
        raise ValueError(f"unknown op {op}")

    def _refresh(self) -> Snap:
        snap = snapshot(
            observe_window=self._observe_window,
            observe_app=self._observe_app,
        )
        self._last = snap
        return snap

    def _scene_message(self, snap: Snap) -> dict[str, Any]:
        self._seq += 1
        return {
            "v": PROTOCOL,
            "type": "scene",
            "seq": self._seq,
            "t": now_ms(),
            "kind": "full",
            "permissions": {
                "screen_recording": False,
                "accessibility": snap.accessibility,
            },
            "displays": [{"id": "d0", "bounds": {"x": 0, "y": 0, "w": 1280, "h": 720}, "scale": 1}],
            "windows": snap.windows,
            "cursor": {"x": 0, "y": 0},
            "focus": snap.focus,
            "observe": snap.observe or snap.focus,
            "damage": [],
            "nodes": snap.nodes,
            "tiles": [],
        }

    def _settle(self) -> None:
        try:
            delay = float(os.environ.get("SCENEUSE_SETTLE", "1"))
        except ValueError:
            delay = 1.0
        if delay > 0:
            time.sleep(delay)

    def _push_scene(self, force: bool = False) -> None:
        del force  # refresh always; only subscribed clients receive
        snap = self._refresh()
        msg = self._scene_message(snap)
        with self._lock:
            conns = [c for c in self._conns.values() if c.subscribed]
        for c in conns:
            c.send(msg)

    def _emit_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                any_sub = any(c.subscribed for c in self._conns.values())
            if any_sub:
                snap = self._refresh()
                msg = self._scene_message(snap)
                with self._lock:
                    conns = [c for c in self._conns.values() if c.subscribed]
                for c in conns:
                    c.send(msg)
            time.sleep(0.4)


def default_sock() -> str:
    return os.environ.get("SCENEUSE_SOCK") or os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "sceneuse.sock"
    )


def main(argv: list[str] | None = None) -> int:
    path = default_sock()
    if argv and len(argv) > 1 and not argv[1].startswith("-"):
        path = argv[1]
    Server(path).serve_forever()
    return 0
