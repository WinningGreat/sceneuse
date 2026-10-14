# sceneuse

Computer-use API whose observation is a **display scene**, not a screenshot.

The OS already knows windows, damage regions, and a UI tree before it rasterizes a frame for the monitor. Intercepting HDMI still leaves you with pixels. sceneuse sits one step earlier: compositor metadata + accessibility, with JPEG tiles only where the tree is silent.

```
display 0 1470x956 @2x
focus: Messages  pid=412  win=w:1234
damage: 2 rects
nodes:
  [n14] button "Send"  (enabled)
  [n9]  textfield "iMessage" value="hello"
tiles: none
```

Vision is warranted only when `tiles` is non-empty.

This is a synthesis, not a vacuum: Playwright MCP (browser a11y snapshots), UFO² / Terminator (desktop UIA/AX), RDP dirty rects, ScreenCaptureKit `dirtyRects`. The product is one streaming Scene/Act protocol.

## Layout

| path | what |
| --- | --- |
| [spec/scene.md](spec/scene.md) | protocol |
| [macos/](macos/) | Swift daemon (`sceneused`) |
| [linux/](linux/) | AT-SPI sandbox daemon + Docker (Xvfb) |
| [android/](android/) | host daemon: adb + uiautomator dump (fixture or device) |
| [ios/](ios/) | host daemon: simctl + optional AXP (`idb`/`iosef`) |
| [GOLDEN.md](GOLDEN.md) | Bake into macOS/Linux guest images + how to host |
| [python/sceneuse](python/sceneuse) | client + compact prompt render |
| [inspector/](inspector/) | local scene graph / damage view |
| [adapters/](adapters/) | Windows, Linux, Android, iOS contracts |

## Host install (macOS)

sceneuse is two processes on the machine the agent uses:

1. **`sceneused`** — compositor/AX daemon (the thing that needs Screen Recording + Accessibility). Prefer `Sceneused.app` so TCC keys off **sceneused**, not Cursor.
2. **MCP stdio** — Cursor (or any MCP client) spawns `python3 -m sceneuse mcp`, which talks NDJSON to `/tmp/sceneuse.sock`. You do not run a second long-lived MCP server yourself.

```sh
make install-macos   # ~/Applications + LaunchAgent + doctor (recommended)
make daemon          # dev: build + open Sceneused.app from repo
make doctor          # socket, permissions, MCP snippet; --fix restarts app
make status          # both permissions should be true
# Point any MCP client at: python3 -m sceneuse mcp (see `make doctor` for JSON)
```

Grant **Screen Recording** and **Accessibility** to **sceneused** in System Settings on first run. Rebuilding the ad-hoc–signed `.app` can look like a new identity — flip the toggles off/on if `status` or `doctor` shows false.


```sh
make inspector       # http://127.0.0.1:8765
make smoke           # one compact scene
make scene           # same, no tiles
make loop            # set + invoke on a local fixture, then read the result
make native          # same loop in Notes (dismisses welcome sheet, new note)
```

`make install-macos` copies `Sceneused.app` to `~/Applications`, installs a LaunchAgent, and runs `doctor`. Dev builds from the repo still use `make daemon`; both need TCC grants after each ad-hoc re-sign.

Linux sandbox (Docker):

```sh
make linux-image
make linux-smoke   # Xvfb + AT-SPI + GTK fixture: hello/status/set/invoke
```

Mobile (same protocol, different socket so they do not steal macOS `/tmp/sceneuse.sock`):

```sh
make android-smoke   # in-memory uiautomator fixture: hello/status/set/invoke
make ios-smoke       # in-memory AXP fixture: hello/status/set/invoke
# live:
# SCENEUSE_SOCK=/tmp/sceneuse-android.sock PYTHONPATH=android python3 -m sceneused
# SCENEUSE_SOCK=/tmp/sceneuse-ios.sock PYTHONPATH=ios python3 -m sceneused
```

Python (no extra deps):

```python
from sceneuse import Client

with Client() as c:
    c.subscribe(tiles=True)
    scene = c.next_scene()
    print(scene.render())
    send = scene.find(role="button", name="Send")
    if send:
        c.invoke(send[0]["id"])
```

Socket: `$SCENEUSE_SOCK` or `/tmp/sceneuse.sock`.

## MCP

stdio server, no extra Python deps. Cursor spawns it from `mcp.json` — do not run a second copy. Daemon must already be running. Framing is newline-delimited JSON-RPC.

```sh
PYTHONPATH=python python3 -m sceneuse mcp
```

Cursor example (`~/.cursor/mcp.json` or project `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "sceneuse": {
      "command": "python3",
      "args": ["-m", "sceneuse", "mcp"],
      "env": {
        "PYTHONPATH": "<repo>/python",
        "SCENEUSE_SOCK": "/tmp/sceneuse.sock"
      }
    }
  }
}
```

Tools: `status`, `scene`, `find`, `invoke`, `set`, `hit`, `drag`, `scroll`, `key`, `raise`, `target`. `scene` / `target` switch the observation handle without raising. `raise` brings a window front when `key` needs it. `hit` / `drag` / `scroll` are pointer geometry (window must be visible, not covered). Compact `scene` text; vision only when `tiles` is non-empty.

## Protocol in one sentence

NDJSON over a Unix socket: `hello` / `status` / `subscribe` / `act`; unsolicited `scene` messages (`full` then `delta`) with windows, damage, pruned nodes, and optional sparse tiles.

## Status

| Adapter | What ships | Live-tested |
| --- | --- | --- |
| macOS | Swift `sceneused` (ScreenCaptureKit + AX) | yes |
| Linux | Python AT-SPI daemon + Docker sandbox | fixture / Xvfb |
| Android | host daemon (`adb` + uiautomator dump) | fixture; device when `adb` is present |
| iOS | host daemon (`simctl` + AXP via `iosef`/`idb`) | Simulator |
| Windows | adapter contract only | — |

## License

[MIT](LICENSE)
