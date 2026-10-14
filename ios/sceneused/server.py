"""NDJSON Unix-socket server for iOS sceneused."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from typing import Any

from . import __version__
from . import axp
from . import simctl
from .tree import Snap, apply_mark, apply_set, load_fixture, now, snapshot_tree

PROTOCOL = 1
ADAPTER = "ios"


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
    def __init__(self, path: str, fixture: str | None = None):
        self.path = path
        self.fixture = fixture or os.environ.get("SCENEUSE_IOS_FIXTURE")
        self._sock: socket.socket | None = None
        self._conns: dict[str, Connection] = {}
        self._lock = threading.Lock()
        self._seq = 0
        self._last: Snap = Snap()
        self._observe_window: str | None = None
        self._observe_app: str | None = None
        self._stop = threading.Event()
        if self.fixture:
            self._last = load_fixture(self.fixture)

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
        mode = f"fixture {self.fixture}" if self.fixture else "simctl"
        print(f"sceneused ios ({mode}) on {self.path}", flush=True)

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

    def _udid(self) -> str | None:
        return simctl.booted_udid()

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
            if self.fixture:
                a11y, capture = True, False
                hint = None
            else:
                udid = self._udid()
                a11y = axp.has_axp()
                capture = bool(udid)
                hint = None
                if not udid:
                    hint = "no booted simulator — open Simulator or set SCENEUSE_IOS_FIXTURE"
                elif not a11y:
                    hint = "install idb or iosef for AXP nodes; simctl identity still works"
            return self._ok(
                conn,
                mid,
                {
                    "permissions": {
                        "screen_recording": capture,
                        "accessibility": a11y,
                    },
                    "socket": self.path,
                    "adapter": ADAPTER,
                    "version": __version__,
                    **({"tcc_hint": hint} if hint else {}),
                    **({"fixture": self.fixture} if self.fixture else {}),
                    **({"udid": self._udid()} if not self.fixture else {}),
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
            self._push_scene()
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
                self._push_scene()
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
                {"window": obs.get("window"), "app": obs.get("app"), "pid": obs.get("pid")},
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
            self._push_scene()
            return self._ok(conn, mid, {"ok": True})

        self._fail(conn, mid, "unknown_type", f"unknown type {typ}")

    def _settle(self) -> None:
        if self.fixture:
            return
        try:
            delay = float(os.environ.get("SCENEUSE_SETTLE", "1"))
        except ValueError:
            delay = 1.0
        if delay > 0:
            time.sleep(delay)

    def _node(self, nid: str) -> dict[str, Any]:
        for n in self._last.nodes:
            if n.get("id") == nid:
                return n
        raise KeyError(f"unknown node {nid}")

    def _center(self, node: dict[str, Any]) -> tuple[float, float]:
        b = node.get("bounds") or {}
        return float(b.get("x", 0)) + float(b.get("w", 0)) / 2, float(b.get("y", 0)) + float(b.get("h", 0)) / 2

    def _act(self, params: dict[str, Any]) -> None:
        op = params.get("op") or ""
        if op == "invoke":
            node = self._node(str(params.get("node") or ""))
            if self.fixture:
                if (node.get("name") or "").lower() == "mark" and self._last.root is not None:
                    apply_mark(self._last.root)
                return
            x, y = self._center(node)
            if not axp.tap_xy(x, y, udid=self._udid()):
                raise PermissionError("invoke needs idb or iosef (AXP/HID)")
            return
        if op == "set":
            node = self._node(str(params.get("node") or ""))
            if "value" not in params:
                raise ValueError("value required")
            value = str(params["value"])
            if self.fixture:
                obj = self._last.node_refs.get(node["id"])
                if obj is None:
                    raise KeyError(f"unknown node {node['id']}")
                apply_set(obj, value)
                return
            x, y = self._center(node)
            if not axp.tap_xy(x, y, udid=self._udid()) or not axp.type_text(value, udid=self._udid()):
                raise PermissionError("set needs idb or iosef")
            return
        if op == "raise":
            app = params.get("app") or self._observe_app
            if self.fixture or not app:
                return
            udid = self._udid()
            if not udid:
                raise PermissionError("no booted simulator")
            bid = simctl.resolve_bundle(udid, str(app))
            if not bid:
                raise KeyError(f"no app matching {app}")
            simctl.launch(udid, bid)
            return
        if op == "hit":
            point = params.get("point") or {}
            x, y = float(point.get("x", 0)), float(point.get("y", 0))
            if self.fixture:
                self._fixture_hit(x, y)
                return
            if not axp.tap_xy(x, y, udid=self._udid()):
                raise PermissionError("hit needs idb or iosef")
            return
        if op in {"drag", "scroll"}:
            if self.fixture:
                return
            if op == "drag":
                frm, to = params.get("from") or {}, params.get("to") or {}
                x0, y0 = float(frm.get("x", 0)), float(frm.get("y", 0))
                x1, y1 = float(to.get("x", 0)), float(to.get("y", 0))
            else:
                point = params.get("point") or {}
                delta = params.get("delta") or {}
                x0, y0 = float(point.get("x", 0)), float(point.get("y", 0))
                x1 = x0 + float(delta.get("x", 0))
                y1 = y0 + float(delta.get("y", 0))
            if not axp.swipe_xy(x0, y0, x1, y1, udid=self._udid()):
                raise PermissionError(f"{op} needs idb or iosef")
            return
        if op == "key":
            if self.fixture:
                return
            raise PermissionError("key needs idb or iosef")
        raise ValueError(f"unknown op {op}")

    def _fixture_hit(self, x: float, y: float) -> None:
        for n in reversed(self._last.nodes):
            b = n.get("bounds") or {}
            nx, ny, nw, nh = float(b.get("x", 0)), float(b.get("y", 0)), float(b.get("w", 0)), float(b.get("h", 0))
            if nx <= x <= nx + nw and ny <= y <= ny + nh and (n.get("name") or "").lower() == "mark":
                if self._last.root is not None:
                    apply_mark(self._last.root)
                return

    def _identity_snap(self) -> Snap:
        snap = Snap()
        udid = self._udid()
        if not udid:
            return snap
        disp = simctl.display(udid)
        name = simctl.device_name(udid)
        bundle = self._observe_app or "com.apple.springboard"
        if self._observe_app:
            resolved = simctl.resolve_bundle(udid, self._observe_app)
            if resolved:
                bundle = resolved
        app_name = name
        apps = simctl.listapps(udid)
        info = apps.get(bundle) or {}
        app_name = str(info.get("CFBundleDisplayName") or info.get("CFBundleName") or bundle)
        bounds = disp["bounds"]
        wid = f"w:{bundle}"
        snap.display = disp
        snap.windows = [
            {
                "id": wid,
                "pid": 0,
                "app": app_name,
                "bundle": bundle,
                "title": name,
                "bounds": bounds,
                "z": 0,
                "focused": True,
                "on_screen": True,
                "occluded": False,
            }
        ]
        snap.focus = {"window": wid, "app": app_name, "pid": 0}
        snap.observe = dict(snap.focus)
        tree = axp.dump_tree(udid)
        if tree:
            built = snapshot_tree(
                tree,
                bundle=bundle,
                app=app_name,
                title=name,
                display_w=bounds["w"],
                display_h=bounds["h"],
                scale=float(disp.get("scale") or 3),
            )
            built.windows = snap.windows
            built.focus = snap.focus
            built.observe = snap.observe
            built.display = disp
            return built
        return snap

    def _refresh(self) -> Snap:
        if self.fixture:
            if self._last.root is None:
                self._last = load_fixture(self.fixture)
            else:
                self._last = snapshot_tree(self._last.root, fixture=True)
            return self._last
        snap = self._identity_snap()
        self._last = snap
        return snap

    def _scene_message(self, snap: Snap) -> dict[str, Any]:
        self._seq += 1
        bounds = (snap.display or {}).get("bounds") or {"x": 0, "y": 0, "w": 402, "h": 874}
        scale = (snap.display or {}).get("scale") or 3
        a11y = snap.accessibility or bool(self.fixture)
        capture = (not self.fixture) and bool(self._udid())
        return {
            "v": PROTOCOL,
            "type": "scene",
            "seq": self._seq,
            "t": now(),
            "kind": "full",
            "permissions": {
                "screen_recording": capture,
                "accessibility": a11y,
            },
            "displays": [{"id": "d0", "bounds": bounds, "scale": scale}],
            "windows": snap.windows,
            "cursor": {"x": 0, "y": 0, "visible": False},
            "focus": snap.focus or {"window": None, "app": None, "pid": None},
            "observe": snap.observe or snap.focus or {},
            "damage": [],
            "nodes": snap.nodes,
            "tiles": [],
            "node_count": len(snap.nodes),
        }

    def _push_scene(self) -> None:
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
                self._push_scene()
            time.sleep(0.5 if self.fixture else 1.5)


def default_sock() -> str:
    return os.environ.get("SCENEUSE_SOCK") or "/tmp/sceneuse-ios.sock"


def main(argv: list[str] | None = None) -> int:
    path = default_sock()
    if argv and len(argv) > 1 and not argv[1].startswith("-"):
        path = argv[1]
    Server(path).serve_forever()
    return 0
