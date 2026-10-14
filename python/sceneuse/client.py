from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

from .scene import Scene

DEFAULT_SOCK = os.environ.get("SCENEUSE_SOCK", "/tmp/sceneuse.sock")


class SceneuseError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Client:
    """NDJSON client for sceneused."""

    def __init__(self, path: str | None = None, timeout: float = 10.0):
        self.path = path or DEFAULT_SOCK
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._buf = b""
        self._last: Scene | None = None
        self._pending: dict[str, dict[str, Any]] = {}
        self._hello: dict[str, Any] | None = None

    def connect(self) -> dict[str, Any]:
        if self._sock:
            return self._hello or {}
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.path)
        self._sock = sock
        self._hello = self._rpc("hello", _retry=False)
        return self._hello

    def reset(self) -> None:
        """Drop connection state (e.g. after daemon restart)."""
        self.close()
        self._hello = None
        self._pending.clear()
        self._buf = b""
        self._last = None

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self) -> "Client":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def status(self) -> dict[str, Any]:
        self.connect()
        return self._rpc("status")

    def subscribe(self, tiles: bool = True, window: str | None = None, app: str | None = None) -> None:
        self.connect()
        params: dict[str, Any] = {"tiles": tiles}
        if window:
            params["window"] = window
        if app:
            params["app"] = app
        self._rpc("subscribe", params)

    def target(self, window: str | None = None, app: str | None = None) -> dict[str, Any]:
        """Set the observation handle. Omit both to follow OS frontmost again."""
        params: dict[str, Any] = {}
        if window:
            params["window"] = window
        if app:
            params["app"] = app
        return self._rpc("target", params)

    def unsubscribe(self) -> None:
        self._rpc("unsubscribe")

    def scenes(self) -> Iterator[Scene]:
        """Yield merged scenes. Call subscribe() first."""
        while True:
            msg = self._read_message()
            if msg.get("type") == "scene":
                self._last = Scene.from_message(msg, self._last)
                yield self._last
            elif msg.get("type") == "error":
                err = msg.get("error") or {}
                raise SceneuseError(err.get("code", "internal"), err.get("message", ""))
            elif msg.get("id"):
                self._pending[str(msg["id"])] = msg

    def next_scene(self, timeout: float | None = None) -> Scene:
        sock = self._require()
        old = sock.gettimeout()
        sock.settimeout(timeout if timeout is not None else self.timeout)
        try:
            return next(self.scenes())
        finally:
            sock.settimeout(old)

    def wait(
        self,
        predicate,
        timeout: float = 12.0,
    ) -> Scene:
        """Next scene that satisfies predicate. Raises TimeoutError with the last render."""
        deadline = time.time() + timeout
        last: Scene | None = self._last
        remaining = timeout
        while remaining > 0:
            try:
                scene = self.next_scene(timeout=min(remaining, 2.0))
            except (TimeoutError, socket.timeout) as e:
                render = last.render() if last else "no scene yet"
                raise TimeoutError(f"timed out waiting for scene\n{render}") from e
            last = scene
            if predicate(scene):
                return scene
            remaining = deadline - time.time()
        render = last.render() if last else "no scene yet"
        raise TimeoutError(f"timed out waiting for scene\n{render}")

    def act(self, **params: Any) -> dict[str, Any]:
        result = dict(self._rpc("act", params) or {})
        if self._last is not None:
            result["scene"] = self._last.render()
        return result

    def invoke(self, node: str, action: str = "press") -> dict[str, Any]:
        return self.act(op="invoke", node=node, action=action)

    def set(self, node: str, value: str) -> dict[str, Any]:
        return self.act(op="set", node=node, value=value)

    def hit(self, window: str, x: float, y: float, button: str = "left") -> dict[str, Any]:
        return self.act(op="hit", window=window, point={"x": x, "y": y}, button=button)

    def key(self, *keys: str) -> dict[str, Any]:
        return self.act(op="key", keys=list(keys))

    def raise_window(self, window: str) -> dict[str, Any]:
        return self.act(op="raise", window=window)

    def scroll(
        self,
        dx: float = 0,
        dy: float = 0,
        window: str | None = None,
        x: float | None = None,
        y: float | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"op": "scroll", "delta": {"x": dx, "y": dy}}
        if window:
            params["window"] = window
        if x is not None and y is not None:
            params["point"] = {"x": x, "y": y}
        return self.act(**params)

    def drag(self, window: str, x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
        return self.act(
            op="drag",
            window=window,
            **{"from": {"x": x0, "y": y0}, "to": {"x": x1, "y": y1}},
        )

    @property
    def last(self) -> Scene | None:
        return self._last

    def _require(self) -> socket.socket:
        self.connect()
        assert self._sock is not None
        return self._sock

    def _rpc(
        self,
        typ: str,
        params: dict[str, Any] | None = None,
        *,
        _retry: bool = True,
    ) -> dict[str, Any]:
        try:
            return self._rpc_once(typ, params)
        except (ConnectionError, BrokenPipeError, OSError) as e:
            if not _retry:
                raise
            if isinstance(e, OSError) and e.errno not in (32, 54, 57, 61, 104, 107):
                raise
            self.reset()
            self.connect()
            return self._rpc_once(typ, params)

    def _rpc_once(self, typ: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        req_id = uuid.uuid4().hex[:12]
        msg: dict[str, Any] = {"v": 1, "type": typ, "id": req_id}
        if params:
            msg["params"] = params
        self._send(msg)
        while True:
            if req_id in self._pending:
                got = self._pending.pop(req_id)
            else:
                got = self._read_message()
                if got.get("type") == "scene":
                    self._last = Scene.from_message(got, self._last)
                    continue
                if got.get("id") and got.get("id") != req_id:
                    self._pending[str(got["id"])] = got
                    continue
            if got.get("type") == "error":
                err = got.get("error") or {}
                raise SceneuseError(err.get("code", "internal"), err.get("message", ""))
            if got.get("type") == "ok":
                return got.get("result") or {}
            raise SceneuseError("internal", f"unexpected reply {got.get('type')}")

    def _send(self, msg: dict[str, Any]) -> None:
        data = (json.dumps(msg, separators=(",", ":")) + "\n").encode()
        sock = self._require()
        with self._lock:
            sock.sendall(data)

    def _read_message(self) -> dict[str, Any]:
        sock = self._require()
        with self._lock:
            while b"\n" not in self._buf:
                chunk = sock.recv(64 * 1024)
                if not chunk:
                    raise ConnectionError("sceneused closed the connection")
                self._buf += chunk
            line, self._buf = self._buf.split(b"\n", 1)
        if not line:
            return self._read_message()
        return json.loads(line.decode())
