"""Health check and fix hints for a local sceneuse install."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .client import DEFAULT_SOCK, Client, SceneuseError


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _mac_app_candidates() -> list[Path]:
    root = _repo_root()
    return [
        root / "macos" / ".build" / "Sceneused.app",
        Path.home() / "Applications" / "Sceneused.app",
        Path("/Applications/Sceneused.app"),
    ]


def _socket_alive(path: str) -> tuple[bool, str]:
    if not os.path.exists(path):
        return False, "socket file missing"
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(path)
        s.close()
        return True, "connected"
    except OSError as e:
        if os.path.exists(path):
            return False, f"stale socket ({e})"
        return False, str(e)


def _open_mac_privacy_panes() -> None:
    if platform.system() != "Darwin":
        return
    for url in (
        "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ScreenCapture",
        "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Accessibility",
    ):
        subprocess.run(["open", url], check=False)


def _restart_mac_daemon(app: Path, sock: str) -> None:
    subprocess.run(["pkill", "-f", "Sceneused.app/Contents/MacOS/sceneused"], check=False)
    subprocess.run(["pkill", "-f", "/macos/.build/release/sceneused"], check=False)
    env = {**os.environ, "SCENEUSE_SOCK": sock}
    subprocess.Popen(["open", str(app)], env=env)


def run_doctor(
    *,
    sock: str | None = None,
    fix: bool = False,
    open_settings: bool = False,
) -> int:
    path = sock or DEFAULT_SOCK
    lines: list[str] = []
    ok = True

    lines.append(f"sceneuse doctor ({__version__})")
    lines.append(f"  socket: {path}")
    lines.append(f"  platform: {platform.system()} {platform.machine()}")

    alive, alive_msg = _socket_alive(path)
    if alive:
        lines.append(f"  daemon: OK ({alive_msg})")
    else:
        ok = False
        lines.append(f"  daemon: FAIL ({alive_msg})")
        app = next((p for p in _mac_app_candidates() if p.is_dir()), None)
        if app and platform.system() == "Darwin":
            lines.append(f"  hint: start Sceneused.app at {app}")
            if fix:
                _restart_mac_daemon(app, path)
                lines.append("  action: opened Sceneused.app (permission prompts may appear)")
        else:
            lines.append("  hint: run `make daemon` from the sceneuse repo")

    status: dict[str, Any] = {}
    hello: dict[str, Any] = {}
    node_count = 0
    if alive:
        try:
            with Client(path=path, timeout=8) as c:
                hello = c._hello or {}
                status = c.status()
                perms = status.get("permissions") or {}
                sr = bool(perms.get("screen_recording"))
                ax = bool(perms.get("accessibility"))
                lines.append(f"  adapter: {status.get('adapter') or hello.get('adapter')}")
                lines.append(f"  screen_recording: {'OK' if sr else 'MISSING'}")
                lines.append(f"  accessibility: {'OK' if ax else 'MISSING'}")
                if status.get("bundle_path"):
                    lines.append(f"  bundle: {status['bundle_path']}")
                if status.get("signing"):
                    lines.append(f"  signing: {status['signing']}")
                if not sr or not ax:
                    ok = False
                    lines.append("")
                    lines.append("  TCC fix (macOS):")
                    lines.append("    1. System Settings → Privacy → Screen Recording + Accessibility")
                    lines.append("    2. Enable sceneused (remove + re-add if already listed)")
                    lines.append("    3. Rebuilds change the ad-hoc signature — re-grant after `make bundle`")
                    if open_settings or fix:
                        _open_mac_privacy_panes()
                        lines.append("  action: opened Privacy settings")
                c.subscribe(tiles=False)
                scene = c.next_scene(timeout=8)
                node_count = len(scene.nodes)
                lines.append(f"  scene nodes: {node_count}")
                if node_count == 0 and (not sr or not ax):
                    lines.append("  hint: empty tree until permissions are granted")
                elif node_count == 0:
                    lines.append("  hint: tree empty — focus a native app with AX (Notes, Settings)")
        except (ConnectionError, OSError, SceneuseError, TimeoutError) as e:
            ok = False
            lines.append(f"  protocol: FAIL ({e})")

    lines.append("")
    repo = _repo_root()
    py = repo / "python"
    mcp = {
        "mcpServers": {
            "sceneuse": {
                "command": shutil.which("python3") or "python3",
                "args": ["-m", "sceneuse", "mcp"],
                "env": {
                    "PYTHONPATH": str(py),
                    "SCENEUSE_SOCK": path,
                    "PYTHONUNBUFFERED": "1",
                },
            }
        }
    }
    lines.append("  MCP snippet (~/.cursor/mcp.json or Claude Desktop config):")
    lines.append(json.dumps(mcp, indent=2))

    print("\n".join(lines))
    return 0 if ok else 1
