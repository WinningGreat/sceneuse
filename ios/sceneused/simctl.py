"""xcrun simctl helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any


class SimctlError(RuntimeError):
    pass


def _run(*args: str, check: bool = True) -> str:
    xcrun = shutil.which("xcrun") or "xcrun"
    try:
        proc = subprocess.run(
            [xcrun, "simctl", *args],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError as e:
        raise SimctlError("xcrun not found") from e
    except subprocess.TimeoutExpired as e:
        raise SimctlError(f"simctl timed out: {' '.join(args)}") from e
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    if check and proc.returncode != 0:
        raise SimctlError((err or out or f"exit {proc.returncode}").strip())
    return out


def booted_udid() -> str | None:
    env = os.environ.get("SCENEUSE_IOS_UDID")
    if env:
        return env
    try:
        data = json.loads(_run("list", "devices", "-j"))
    except (SimctlError, json.JSONDecodeError):
        return None
    for _runtime, devices in (data.get("devices") or {}).items():
        for d in devices:
            if d.get("state") == "Booted":
                return str(d.get("udid"))
    return None


def getenv(udid: str, key: str) -> str:
    return _run("getenv", udid, key, check=False).strip()


def display(udid: str) -> dict[str, Any]:
    try:
        scale = float(getenv(udid, "SIMULATOR_MAINSCREEN_SCALE") or 3)
    except ValueError:
        scale = 3.0
    try:
        w_px = float(getenv(udid, "SIMULATOR_MAINSCREEN_WIDTH") or 0)
        h_px = float(getenv(udid, "SIMULATOR_MAINSCREEN_HEIGHT") or 0)
    except ValueError:
        w_px = h_px = 0
    scale = scale if scale > 0 else 1.0
    w = (w_px / scale) if w_px else 402
    h = (h_px / scale) if h_px else 874
    return {
        "id": "d0",
        "bounds": {"x": 0.0, "y": 0.0, "w": w, "h": h},
        "scale": scale,
    }


def device_name(udid: str) -> str:
    return getenv(udid, "SIMULATOR_DEVICE_NAME") or "iOS Simulator"


def listapps(udid: str) -> dict[str, dict[str, Any]]:
    raw = _run("listapps", udid, check=False)
    if not raw.strip():
        return {}
    # simctl listapps prints a legacy plist-ish dump; try json then a tiny parser.
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    except json.JSONDecodeError:
        pass
    apps: dict[str, dict[str, Any]] = {}
    current: str | None = None
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith('"') and s.endswith('" =     {') or (s.startswith('"') and " =     {" in s):
            current = s.split('"', 2)[1]
            apps[current] = {"CFBundleIdentifier": current}
        elif current and "CFBundleDisplayName" in s:
            parts = s.split("=", 1)
            if len(parts) == 2:
                apps[current]["CFBundleDisplayName"] = parts[1].strip().strip(";").strip('"')
        elif current and "CFBundleName" in s:
            parts = s.split("=", 1)
            if len(parts) == 2:
                apps[current].setdefault("CFBundleName", parts[1].strip().strip(";").strip('"'))
    return apps


def launch(udid: str, bundle: str) -> None:
    _run("launch", udid, bundle)


def screenshot_ok(udid: str) -> bool:
    try:
        _run("io", udid, "screenshot", "--type=png", "/dev/null", check=True)
        return True
    except SimctlError:
        return False


def resolve_bundle(udid: str, app: str) -> str | None:
    key = app.lower()
    apps = listapps(udid)
    if app in apps:
        return app
    for bid, info in apps.items():
        blob = " ".join(
            str(info.get(k) or "")
            for k in ("CFBundleIdentifier", "CFBundleDisplayName", "CFBundleName")
        ).lower()
        if key in bid.lower() or key in blob:
            return bid
    # simctl listapps is a legacy plist dump; a dotted id is still launchable.
    if "." in app and " " not in app:
        return app
    return None
