"""Live adb snapshot and input."""

from __future__ import annotations

import re
import time

from .adb import Adb, AdbError
from .uia_snap import Snap, snapshot_xml

_SIZE = re.compile(r"(?:Override|Physical) size:\s*(\d+)x(\d+)")
_DENSITY = re.compile(r"(?:Override|Physical) density:\s*(\d+)")
_FOCUS = re.compile(
    r"(?:mCurrentFocus|mFocusedApp|mResumedActivity).*?([a-zA-Z0-9._]+)(?:/([a-zA-Z0-9._$]+))?"
)


def _wm_geometry(adb: Adb) -> tuple[float, float, float]:
    size_txt = adb.run("shell", "wm", "size", check=False)
    dens_txt = adb.run("shell", "wm", "density", check=False)
    w = h = 0
    for m in _SIZE.finditer(size_txt):
        w, h = int(m.group(1)), int(m.group(2))
    density = 160
    for m in _DENSITY.finditer(dens_txt):
        density = int(m.group(1))
    scale = max(density / 160.0, 0.5)
    if w <= 0 or h <= 0:
        w, h = 1080, 2400
    return w / scale, h / scale, scale


def _focus_package(adb: Adb) -> tuple[str, str | None]:
    text = adb.run("shell", "dumpsys", "window", "windows", check=False)
    if not text.strip():
        text = adb.run("shell", "dumpsys", "activity", "activities", check=False)
    pkg, activity = "unknown", None
    for m in _FOCUS.finditer(text):
        pkg = m.group(1)
        activity = m.group(2)
    return pkg, activity


def _pidof(adb: Adb, package: str) -> int:
    out = adb.run("shell", "pidof", "-s", package, check=False).strip()
    try:
        return int(out.split()[0])
    except (ValueError, IndexError):
        return 0


def _dump_xml(adb: Adb) -> str:
    adb.run("shell", "uiautomator", "dump", "--compressed", "/sdcard/sceneuse-dump.xml", check=True)
    xml = adb.run("exec-out", "cat", "/sdcard/sceneuse-dump.xml", check=True)
    if "<hierarchy" not in xml and "<node" not in xml:
        raise AdbError("uiautomator dump produced no hierarchy")
    # drop the "UI hierchary dumped to:" line if cat mixed it
    idx = xml.find("<?xml")
    if idx == -1:
        idx = xml.find("<hierarchy")
    return xml[idx:] if idx >= 0 else xml


def snapshot_live(adb: Adb, *, observe_app: str | None = None) -> Snap:
    try:
        dw, dh, scale = _wm_geometry(adb)
        pkg, activity = _focus_package(adb)
        xml = _dump_xml(adb)
    except AdbError:
        return Snap()
    return snapshot_xml(
        xml,
        scale=scale,
        display_w=dw,
        display_h=dh,
        package=pkg,
        title=activity or pkg,
        pid=_pidof(adb, pkg),
        fixture=False,
        observe_app=observe_app,
    )


def logical_to_px(x: float, y: float, scale: float) -> tuple[int, int]:
    return int(round(x * scale)), int(round(y * scale))


def tap(adb: Adb, x: float, y: float, scale: float, *, duration_ms: int = 0) -> None:
    px, py = logical_to_px(x, y, scale)
    if duration_ms > 0:
        adb.run("shell", "input", "swipe", str(px), str(py), str(px), str(py), str(duration_ms))
        return
    adb.run("shell", "input", "tap", str(px), str(py))


def swipe(
    adb: Adb,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    scale: float,
    duration_ms: int = 300,
) -> None:
    a = logical_to_px(x0, y0, scale)
    b = logical_to_px(x1, y1, scale)
    adb.run(
        "shell",
        "input",
        "swipe",
        str(a[0]),
        str(a[1]),
        str(b[0]),
        str(b[1]),
        str(duration_ms),
    )


def set_text(adb: Adb, value: str) -> None:
    # Prefer clipboard paste so unicode survives; fall back to input text.
    escaped = value.replace("'", "'\\''")
    out = adb.run("shell", "cmd", "clipboard", "set-text", "--", value, check=False)
    if "Unknown command" in out or "not found" in out.lower():
        safe = value.replace(" ", "%s").replace("'", "")
        adb.run("shell", "input", "text", safe)
        return
    adb.run("shell", "input", "keyevent", "279", check=False)  # KEYCODE_PASTE
    del escaped


_KEYEVENT = {
    "return": "66",
    "enter": "66",
    "tab": "61",
    "escape": "111",
    "space": "62",
    "back": "4",
    "home": "3",
    "delete": "67",
    "backspace": "67",
    "up": "19",
    "down": "20",
    "left": "21",
    "right": "22",
}


def keyevent(adb: Adb, keys: list[str]) -> None:
    letters: list[str] = []
    for tok in keys:
        t = tok.lower()
        if t in {"cmd", "ctrl", "alt", "shift", "fn"}:
            raise PermissionError(f"{t} is unsupported on android")
        if t in _KEYEVENT:
            if letters:
                adb.run("shell", "input", "text", "".join(letters).replace(" ", "%s"))
                letters = []
            adb.run("shell", "input", "keyevent", _KEYEVENT[t])
            continue
        if len(tok) == 1:
            letters.append(tok)
            continue
        raise ValueError(f"unknown key {tok}")
    if letters:
        adb.run("shell", "input", "text", "".join(letters).replace(" ", "%s"))


def launch(adb: Adb, app: str) -> None:
    pkg = app.strip()
    # substring match against dumpsys package
    if "." not in pkg or pkg != pkg.lower() and "/" in pkg:
        pass
    try:
        adb.run(
            "shell",
            "monkey",
            "-p",
            pkg,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
        return
    except AdbError:
        pass
    # resolve substring via pm list
    listed = adb.run("shell", "pm", "list", "packages", check=False)
    matches = [
        line.split(":", 1)[-1].strip()
        for line in listed.splitlines()
        if pkg.lower() in line.lower()
    ]
    if not matches:
        raise KeyError(f"no package matching {app}")
    adb.run(
        "shell",
        "monkey",
        "-p",
        matches[0],
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
    )
    time.sleep(0.3)
