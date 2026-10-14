"""Close the loop: open a fixture, set a field, invoke a button, read the result."""

from __future__ import annotations

import http.server
import os
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "loop.html"
PORT = int(os.environ.get("SCENEUSE_LOOP_PORT", "8766"))
URL = f"http://127.0.0.1:{PORT}/loop.html"
PHRASE = "hello Ada"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args: object) -> None:
        pass


class ReuseServer(socketserver.TCPServer):
    allow_reuse_address = True


def serve() -> socketserver.TCPServer:
    httpd = ReuseServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def open_fixture() -> None:
    subprocess.run(["open", "-a", "Safari", URL], check=False)
    subprocess.run(
        ["osascript", "-e", 'tell application "Safari" to activate'],
        check=False,
        capture_output=True,
    )


def hit_center(client, node: dict) -> None:
    bounds = node.get("bounds") or {}
    win_id = node.get("window")
    if not win_id or not bounds:
        raise RuntimeError(f"node {node.get('id')} has no bounds/window")
    scene = client.last
    window = scene.window(win_id) if scene else None
    if not window:
        raise RuntimeError(f"unknown window {win_id}")
    wb = window.get("bounds") or {}
    x = float(bounds["x"]) + float(bounds.get("w", 0)) / 2 - float(wb.get("x") or 0)
    y = float(bounds["y"]) + float(bounds.get("h", 0)) / 2 - float(wb.get("y") or 0)
    client.hit(win_id, x, y)


def type_text(client, text: str) -> None:
    for ch in text:
        if ch == " ":
            client.key("space")
        elif ch.isupper():
            client.key("shift", ch.lower())
        else:
            client.key(ch)


def main() -> int:
    sys.path.insert(0, str(ROOT.parent))
    from sceneuse.client import Client, SceneuseError

    if not HTML.is_file():
        print(f"missing {HTML}", file=sys.stderr)
        return 1

    httpd = serve()
    open_fixture()
    time.sleep(0.8)

    try:
        with Client() as c:
            c.subscribe(tiles=False)
            print(f"opened {URL}", flush=True)
            scene = c.wait(
                lambda s: s.find(role="button", name="Greet")
                and (s.find(role="textfield", name="Name") or s.find(role="textfield")),
                timeout=18,
            )
            print("--- before ---")
            print(scene.render())

            field = (scene.find(role="textfield", name="Name") or scene.find(role="textfield"))[0]
            button = scene.find(role="button", name="Greet")[0]
            print(f"set {field['id']} -> Ada", flush=True)
            typed = False
            try:
                c.set(field["id"], "Ada")
            except SceneuseError as e:
                print(f"set via AX failed ({e}); typing", flush=True)
                hit_center(c, field)
                time.sleep(0.15)
                type_text(c, "Ada")
                typed = True

            print(f"invoke {button['id']}", flush=True)
            try:
                c.invoke(button["id"])
            except SceneuseError as e:
                print(f"invoke via AX failed ({e}); clicking", flush=True)
                # ids may have shifted; re-read once
                scene = c.next_scene(timeout=4)
                button = scene.find(role="button", name="Greet")[0] if scene.find(role="button", name="Greet") else button
                hit_center(c, button)

            result = c.wait(lambda s: s.mentions(PHRASE), timeout=10)
            print("--- after ---")
            print(result.render())
            print(f"ok: scene mentions {PHRASE!r} (typed={typed})")
            return 0
    except (ConnectionError, FileNotFoundError, OSError) as e:
        print(f"loop failed to connect: {e}", file=sys.stderr)
        print("start the daemon: make daemon", file=sys.stderr)
        return 1
    except (TimeoutError, SceneuseError, RuntimeError) as e:
        print(f"loop failed: {e}", file=sys.stderr)
        return 1
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
