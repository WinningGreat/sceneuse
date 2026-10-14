"""Optional AXP dump via idb or iosef (`iosef` on PATH, or `uvx iosef`)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

# iosef --json wraps a text tree: AXRole "Name" (cx±hw, cy±hh) value="..." [traits]
_LINE = re.compile(
    r"^(?P<indent>\s*)(?P<role>AX[A-Za-z]+)"
    r"(?:\s+\"(?P<name>[^\"]*)\")?"
    r"(?:\s+\((?P<cx>-?[\d.]+)±(?P<hw>[\d.]+),\s*(?P<cy>-?[\d.]+)±(?P<hh>[\d.]+)\))?"
    r"(?:\s+value=\"(?P<value>[^\"]*)\")?"
    r"(?:\s+\[(?P<traits>[^\]]*)\])?"
    r"\s*$"
)


def _iosef_cmd() -> list[str] | None:
    found = shutil.which("iosef")
    if found:
        return [found]
    uvx = shutil.which("uvx")
    if uvx:
        return [uvx, "iosef"]
    return None


def _device_args(udid: str | None) -> list[str]:
    args = ["--global"]
    device = udid or os.environ.get("SCENEUSE_IOS_UDID")
    if device:
        args.extend(["--device", device])
    return args


def _run(argv: list[str], timeout: float = 20.0) -> str | None:
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    out = (proc.stdout or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        return None
    return out


def _json_ok(out: str | None) -> tuple[bool, Any]:
    if out is None:
        return False, None
    if not out.strip():
        return True, None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return True, out
    if isinstance(data, dict) and data.get("isError"):
        return False, data
    return True, data


def parse_iosef_text(text: str) -> dict[str, Any] | None:
    """Parse iosef's indented AX text tree into a nested dict for snapshot_tree."""
    merged: list[str] = []
    buf = ""
    for line in text.splitlines():
        buf = line if not buf else buf + "\n" + line
        if buf.count('"') % 2 == 0:
            merged.append(buf)
            buf = ""
    if buf:
        merged.append(buf)

    stack: list[tuple[int, dict[str, Any]]] = []
    root: dict[str, Any] | None = None
    for line in merged:
        if not line.strip():
            continue
        m = _LINE.match(line.replace("\n", " "))
        if not m:
            continue
        indent = len(m.group("indent").expandtabs(2))
        node: dict[str, Any] = {"role": m.group("role"), "children": []}
        if m.group("name"):
            node["name"] = " ".join(m.group("name").split())
        if m.group("value"):
            node["value"] = m.group("value")
        if m.group("cx") is not None:
            cx, hw = float(m.group("cx")), float(m.group("hw"))
            cy, hh = float(m.group("cy")), float(m.group("hh"))
            node["bounds"] = {"x": cx - hw, "y": cy - hh, "w": hw * 2, "h": hh * 2}
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            root = node
        stack.append((indent, node))
    return root


def unwrap_axp(data: Any) -> dict[str, Any] | None:
    if data is None:
        return None
    if isinstance(data, str):
        return parse_iosef_text(data)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if data[0].get("role") or data[0].get("AXRole"):
            return {"role": "window", "children": data}
        texts = [c.get("text") for c in data if isinstance(c, dict) and c.get("text")]
        if texts:
            return parse_iosef_text("\n".join(str(t) for t in texts))
        return None
    if not isinstance(data, dict):
        return None
    if data.get("isError"):
        return None
    if data.get("role") or data.get("AXRole") or data.get("children") or data.get("AXChildren"):
        if data.get("content") and not (data.get("role") or data.get("AXRole") or data.get("children")):
            pass
        else:
            return data
    content = data.get("content")
    if isinstance(content, list):
        return unwrap_axp(content)
    if isinstance(content, str):
        return parse_iosef_text(content)
    return None


def dump_tree(udid: str | None = None) -> dict[str, Any] | None:
    cmd = _iosef_cmd()
    if cmd:
        out = _run([*cmd, "describe", "--json", *_device_args(udid)])
        ok, data = _json_ok(out)
        if ok:
            tree = unwrap_axp(data)
            if tree:
                return tree
    idb = shutil.which("idb")
    if idb:
        out = _run([idb, "ui", "describe-all", "--json"])
        if out:
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                data = None
            tree = unwrap_axp(data)
            if tree:
                return tree
    return None


def tap_xy(x: float, y: float, udid: str | None = None) -> bool:
    cmd = _iosef_cmd()
    if cmd:
        out = _run(
            [*cmd, "tap", "--x", str(int(round(x))), "--y", str(int(round(y))), *_device_args(udid)]
        )
        ok, _ = _json_ok(out)
        return ok
    idb = shutil.which("idb")
    if idb:
        return _run([idb, "ui", "tap", str(int(round(x))), str(int(round(y)))]) is not None
    return False


def swipe_xy(x0: float, y0: float, x1: float, y1: float, udid: str | None = None) -> bool:
    cmd = _iosef_cmd()
    if cmd:
        out = _run(
            [
                *cmd,
                "swipe",
                "--x-start",
                str(int(round(x0))),
                "--y-start",
                str(int(round(y0))),
                "--x-end",
                str(int(round(x1))),
                "--y-end",
                str(int(round(y1))),
                *_device_args(udid),
            ]
        )
        ok, _ = _json_ok(out)
        return ok
    idb = shutil.which("idb")
    if idb:
        return (
            _run(
                [
                    idb,
                    "ui",
                    "swipe",
                    str(int(round(x0))),
                    str(int(round(y0))),
                    str(int(round(x1))),
                    str(int(round(y1))),
                ]
            )
            is not None
        )
    return False


def type_text(value: str, udid: str | None = None) -> bool:
    cmd = _iosef_cmd()
    if cmd:
        out = _run([*cmd, "type", "--text", value, *_device_args(udid)])
        ok, _ = _json_ok(out)
        return ok
    idb = shutil.which("idb")
    if idb:
        return _run([idb, "ui", "text", value]) is not None
    return False


def has_axp() -> bool:
    return bool(_iosef_cmd() or shutil.which("idb"))
