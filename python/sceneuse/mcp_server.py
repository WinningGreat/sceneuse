"""stdio MCP server: Scene + Act tools over the local daemon."""

from __future__ import annotations

import json
import sys
from typing import Any

from . import __version__
from .client import Client, SceneuseError

TOOLS: list[dict[str, Any]] = [
    {
        "name": "status",
        "description": "Daemon adapter and TCC permissions (screen recording, accessibility).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "scene",
        "description": (
            "Read the compositor scene as compact text. nodes are the AX tree of the "
            "observation handle (observe), which can be a background window. "
            "focus is OS frontmost and may be Cursor. Pass window (w:123) or app to "
            "switch the handle; omit both to follow frontmost. Raise a window separately "
            "when the OS needs it in front (key). Never dumps screenshots."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_tiles": {
                    "type": "boolean",
                    "description": "Subscribe with sparse JPEG tiles (default false).",
                },
                "window": {
                    "type": "string",
                    "description": "Observe this window id (e.g. w:54405). Does not raise it.",
                },
                "app": {
                    "type": "string",
                    "description": "Observe a window of this app (substring, e.g. Notes). Does not raise it.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "find",
        "description": "Find nodes in the latest scene by role and/or name substring.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "name": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "invoke",
        "description": "Perform an AX action on a node id from the latest scene (default press). Returns the scene about a second later.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {"type": "string"},
                "action": {"type": "string", "default": "press"},
            },
            "required": ["node"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set",
        "description": "Set a text field node's value (node id from the latest scene). Returns the scene about a second later.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["node", "value"],
            "additionalProperties": False,
        },
    },
    {
        "name": "hit",
        "description": (
            "Click a window-local point (logical points, origin top-left of that window). "
            "The window must be visible and not covered at that point. "
            "Returns the scene about a second later."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "window": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "button": {"type": "string", "enum": ["left", "right", "double"]},
            },
            "required": ["window", "x", "y"],
            "additionalProperties": False,
        },
    },
    {
        "name": "drag",
        "description": (
            "Click-drag in a window: press at (x,y), move to (to_x,to_y), release. "
            "Window-local logical points. Window must be visible and not covered along the path. "
            "Returns the scene about a second later."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "window": {"type": "string"},
                "x": {"type": "number", "description": "Start, window-local."},
                "y": {"type": "number"},
                "to_x": {"type": "number", "description": "End, window-local."},
                "to_y": {"type": "number"},
            },
            "required": ["window", "x", "y", "to_x", "to_y"],
            "additionalProperties": False,
        },
    },
    {
        "name": "scroll",
        "description": (
            "Mouse wheel. delta y>0 scrolls up (content moves down). "
            "Optional window + x,y is the window-local point to wheel over. "
            "Returns the scene about a second later."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dx": {"type": "number", "description": "Horizontal wheel delta (points)."},
                "dy": {"type": "number", "description": "Vertical wheel delta (points)."},
                "window": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "key",
        "description": "Press keys into the OS-frontmost app. Raise the target window first if it is not front. Tokens: cmd, shift, alt, ctrl, letters, return, tab, escape, space. Returns the scene about a second later.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key tokens in order, modifiers first.",
                }
            },
            "required": ["keys"],
            "additionalProperties": False,
        },
    },
    {
        "name": "raise",
        "description": "Bring a window to the front. Use when key (or an app) requires frontmost. Looking/set/invoke can use a background handle without this. Returns the scene about a second later.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window": {"type": "string", "description": "Window id from the scene (w:123)."},
                "app": {"type": "string", "description": "If window omitted, first on-screen window of this app."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "target",
        "description": (
            "Set the observation handle without raising. Later scene/find/set/invoke "
            "use that window's tree. Omit window and app to follow OS frontmost again."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "window": {"type": "string"},
                "app": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
]


class Server:
    def __init__(self) -> None:
        self.client: Client | None = None
        self.tiles = False
        self.subscribed = False

    def ensure(self, tiles: bool | None = None, *, subscribe: bool = True) -> Client:
        if tiles is not None:
            self.tiles = tiles
        if self.client is None:
            self.client = Client()
            self.client.connect()
        if not subscribe:
            return self.client
        if not self.subscribed:
            self.client.subscribe(tiles=self.tiles)
            self.subscribed = True
        elif tiles is True and not self.tiles:
            self.client.unsubscribe()
            self.client.subscribe(tiles=True)
            self.tiles = True
            self.subscribed = True
        return self.client

    def _window_id(self, c: Client, args: dict[str, Any], *, required: bool) -> str | None:
        wid = (args.get("window") or "").strip()
        if wid:
            return wid
        app = (args.get("app") or "").strip()
        if app and c.last is not None:
            needle = app.lower()
            for w in c.last.windows:
                if needle in (w.get("app") or "").lower():
                    return (w.get("id") or "") or None
        if required:
            raise ValueError("window or app required")
        return None

    def call(self, name: str, args: dict[str, Any]) -> str:
        try:
            return self._call_impl(name, args)
        except (ConnectionError, BrokenPipeError, OSError) as e:
            if isinstance(e, OSError) and e.errno not in (32, 54, 57, 61, 104, 107):
                raise
            if self.client:
                self.client.reset()
            self.client = None
            self.subscribed = False
            return self._call_impl(name, args)

    def _call_impl(self, name: str, args: dict[str, Any]) -> str:
        if name == "status":
            return json.dumps(self.ensure(subscribe=False).status(), indent=2)
        if name == "scene":
            c = self.ensure(tiles=bool(args.get("include_tiles")))
            window = (args.get("window") or "").strip() or None
            app = (args.get("app") or "").strip() or None
            if window or app:
                c.target(window=window, app=app)
                def _match(s, w=window, a=app) -> bool:
                    obs = s.observe or {}
                    if w and obs.get("window") == w:
                        return True
                    if a and a.lower() in (obs.get("app") or "").lower():
                        return True
                    return False
                if c.last is not None and _match(c.last):
                    scene = c.last
                else:
                    scene = c.wait(_match, timeout=8)
            else:
                scene = c.next_scene(timeout=8)
            text = scene.render()
            if args.get("include_tiles"):
                tiles = scene.tiles or []
                extra = [
                    {
                        "rect": t.get("rect"),
                        "mime": t.get("mime"),
                        "bytes": len(t.get("data") or ""),
                    }
                    for t in tiles
                ]
                return text + "\n" + json.dumps({"tiles": extra})
            return text
        if name == "find":
            c = self.ensure()
            scene = c.last or c.next_scene(timeout=8)
            hits = scene.find(role=args.get("role"), name=args.get("name"))
            slim = [
                {
                    "id": n.get("id"),
                    "role": n.get("role"),
                    "name": n.get("name"),
                    "value": n.get("value"),
                    "actions": n.get("actions"),
                    "window": n.get("window"),
                }
                for n in hits[:40]
            ]
            return json.dumps(slim, indent=2)
        if name == "invoke":
            c = self.ensure()
            if c.last is None:
                c.next_scene(timeout=8)
            c.invoke(args["node"], args.get("action") or "press")
            return (c.last.render() if c.last else "ok")
        if name == "set":
            c = self.ensure()
            if c.last is None:
                c.next_scene(timeout=8)
            c.set(args["node"], args["value"])
            return (c.last.render() if c.last else "ok")
        if name == "hit":
            c = self.ensure()
            if c.last is None:
                c.next_scene(timeout=8)
            wid = self._window_id(c, args, required=True)
            c.hit(wid, float(args["x"]), float(args["y"]), args.get("button") or "left")
            return (c.last.render() if c.last else "ok")
        if name == "drag":
            c = self.ensure()
            if c.last is None:
                c.next_scene(timeout=8)
            wid = self._window_id(c, args, required=True)
            c.drag(
                wid,
                float(args["x"]),
                float(args["y"]),
                float(args["to_x"]),
                float(args["to_y"]),
            )
            return (c.last.render() if c.last else "ok")
        if name == "scroll":
            c = self.ensure()
            wid = (args.get("window") or "").strip() or None
            x = args.get("x")
            y = args.get("y")
            c.scroll(
                dx=float(args.get("dx") or 0),
                dy=float(args.get("dy") or 0),
                window=wid,
                x=float(x) if x is not None else None,
                y=float(y) if y is not None else None,
            )
            return (c.last.render() if c.last else "ok")
        if name == "key":
            keys = args.get("keys") or []
            if not isinstance(keys, list) or not keys:
                raise ValueError("keys must be a non-empty array")
            c = self.ensure()
            c.key(*[str(k) for k in keys])
            return (c.last.render() if c.last else "ok")
        if name == "raise":
            c = self.ensure()
            if c.last is None:
                c.next_scene(timeout=8)
            wid = self._window_id(c, args, required=True)
            c.raise_window(wid)
            return (c.last.render() if c.last else "ok")
        if name == "target":
            c = self.ensure()
            if c.last is None:
                c.next_scene(timeout=8)
            window = (args.get("window") or "").strip() or None
            app = (args.get("app") or "").strip() or None
            return json.dumps(c.target(window=window, app=app))
        raise ValueError(f"unknown tool {name}")


def _read() -> dict[str, Any] | None:
    """One JSON-RPC message. Cursor (and MCP stdio) is newline-delimited JSON.
    Content-Length (LSP) framing is still accepted for older clients.
    """
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        raw = line.strip()
        if not raw:
            continue
        if raw.lower().startswith(b"content-length:"):
            n = int(raw.split(b":", 1)[1].strip() or b"0")
            while True:
                header = sys.stdin.buffer.readline()
                if not header or header in (b"\r\n", b"\n"):
                    break
            if n <= 0:
                return None
            body = sys.stdin.buffer.read(n)
            return json.loads(body.decode("utf-8"))
        return json.loads(raw.decode("utf-8"))


def _write(msg: dict[str, Any]) -> None:
    sys.stdout.buffer.write(json.dumps(msg, separators=(",", ":")).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def _result(req_id: Any, text: str, is_error: bool = False) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        },
    }


def serve() -> None:
    server = Server()
    while True:
        msg = _read()
        if msg is None:
            return
        meth = msg.get("method")
        req_id = msg.get("id")
        # Notifications (no id, or notifications/*) must not get a reply.
        if req_id is None or meth is None or meth.startswith("notifications/"):
            continue
        if meth == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "sceneuse", "version": __version__},
                    },
                }
            )
            continue
        if meth == "ping":
            _write({"jsonrpc": "2.0", "id": req_id, "result": {}})
            continue
        if meth == "tools/list":
            _write({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
            continue
        if meth == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name") or ""
            args = params.get("arguments") or {}
            try:
                text = server.call(name, args if isinstance(args, dict) else {})
                _write(_result(req_id, text))
            except (SceneuseError, ConnectionError, OSError, ValueError, TimeoutError, KeyError) as e:
                _write(_result(req_id, str(e), is_error=True))
            continue
        _write(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"method not found: {meth}"},
            }
        )
