"""Nested AX / fixture JSON → scene nodes. Fixture mode mutates the tree in memory."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .roles import INTERACTIVE, normalize_role


@dataclass
class Snap:
    windows: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    focus: dict[str, Any] = field(default_factory=dict)
    observe: dict[str, Any] = field(default_factory=dict)
    node_refs: dict[str, dict[str, Any]] = field(default_factory=dict)
    accessibility: bool = False
    display: dict[str, Any] = field(default_factory=dict)
    root: dict[str, Any] | None = None
    bundle: str = "dev.sceneuse.fixture"
    fixture: bool = False


def now() -> float:
    return time.time()


def _frame(obj: dict[str, Any]) -> dict[str, float] | None:
    raw = obj.get("bounds") or obj.get("frame") or obj.get("AXFrame")
    if isinstance(raw, str):
        # "{{x, y}, {w, h}}"
        nums = []
        cur = ""
        for ch in raw:
            if ch in "0123456789.-":
                cur += ch
            elif cur:
                nums.append(float(cur))
                cur = ""
        if cur:
            nums.append(float(cur))
        if len(nums) >= 4:
            x, y, w, h = nums[0], nums[1], nums[2], nums[3]
            if w > 0 and h > 0:
                return {"x": x, "y": y, "w": w, "h": h}
        return None
    if not isinstance(raw, dict):
        return None
    x = float(raw.get("x", 0))
    y = float(raw.get("y", 0))
    w = float(raw.get("w", raw.get("width", 0)))
    h = float(raw.get("h", raw.get("height", 0)))
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _name(obj: dict[str, Any]) -> str | None:
    for k in ("name", "AXLabel", "label", "title", "AXTitle", "text"):
        v = obj.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _value(obj: dict[str, Any]) -> str | None:
    for k in ("value", "AXValue"):
        v = obj.get(k)
        if v is not None and v != "":
            return str(v)
    return None


def _role(obj: dict[str, Any]) -> str:
    return normalize_role(
        obj.get("role") or obj.get("AXRole") or obj.get("type") or obj.get("kind")
    )


def _children(obj: dict[str, Any]) -> list[dict[str, Any]]:
    for k in ("children", "AXChildren", "content"):
        v = obj.get(k)
        if isinstance(v, list):
            return [c for c in v if isinstance(c, dict)]
    return []


def flatten(
    root: dict[str, Any],
    *,
    window_id: str,
    max_nodes: int = 200,
    max_depth: int = 24,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    refs: dict[str, dict[str, Any]] = {}

    def walk(obj: dict[str, Any], depth: int, parent: str | None) -> None:
        if len(nodes) >= max_nodes or depth > max_depth:
            return
        role = _role(obj)
        name = _name(obj)
        value = _value(obj)
        bounds = _frame(obj)
        states = list(obj.get("states") or [])
        if obj.get("enabled", True) and "enabled" not in states:
            states.append("enabled")
        if role in {"textfield", "textarea"} and "editable" not in states:
            states.append("editable")
        focused = bool(obj.get("focused") or obj.get("AXFocused"))
        if focused and "focused" not in states:
            states.append("focused")
        actions = list(obj.get("actions") or [])
        if not actions and role in INTERACTIVE:
            actions = ["press"]
        keep = (
            role in INTERACTIVE
            or role in {"window", "dialog", "web", "text", "heading", "sheet"}
            or (name and role not in {"group", "unknown"})
            or depth == 0
        )
        nid: str | None = None
        if keep:
            nid = f"n{len(nodes)}"
            node: dict[str, Any] = {
                "id": nid,
                "role": role,
                "window": window_id,
                "states": states,
                "actions": actions,
                "tags": [],
            }
            if name:
                node["name"] = name
            if value is not None and role in {"textfield", "textarea", "text", "slider"}:
                node["value"] = value
            if bounds:
                node["bounds"] = bounds
            if parent:
                node["parent"] = parent
            if focused:
                node["tags"].append("focus")
            nodes.append(node)
            refs[nid] = obj
        for child in _children(obj):
            walk(child, depth + 1, nid or parent)

    walk(root, 0, None)
    return nodes, refs


def _tag_target(nodes: list[dict[str, Any]]) -> None:
    for n in nodes:
        if "focus" in (n.get("tags") or []):
            n["tags"].append("target")
            return
    for want in ("textfield", "textarea", "button"):
        for n in nodes:
            if n.get("role") == want:
                n.setdefault("tags", []).append("target")
                return


def snapshot_tree(
    root: dict[str, Any],
    *,
    bundle: str = "dev.sceneuse.fixture",
    app: str | None = None,
    title: str | None = None,
    display_w: float = 402,
    display_h: float = 874,
    scale: float = 3,
    pid: int = 0,
    fixture: bool = False,
) -> Snap:
    snap = Snap(root=root, bundle=bundle, fixture=fixture, accessibility=True)
    fr = _frame(root)
    if fr:
        display_w, display_h = fr["w"], fr["h"]
    bounds = {"x": 0.0, "y": 0.0, "w": display_w, "h": display_h}
    snap.display = {"id": "d0", "bounds": dict(bounds), "scale": scale}
    app_name = app or _name(root) or bundle.rsplit(".", 1)[-1]
    wid = f"w:{bundle}"
    win = {
        "id": wid,
        "pid": pid,
        "app": app_name,
        "bundle": bundle,
        "title": title or app_name,
        "bounds": bounds,
        "z": 0,
        "focused": True,
        "on_screen": True,
        "occluded": False,
    }
    snap.windows = [win]
    snap.focus = {"window": wid, "app": app_name, "pid": pid}
    snap.observe = dict(snap.focus)
    nodes, refs = flatten(root, window_id=wid)
    _tag_target(nodes)
    snap.nodes = nodes
    snap.node_refs = refs
    return snap


def apply_set(obj: dict[str, Any], value: str) -> None:
    obj["value"] = value


def apply_mark(root: dict[str, Any]) -> None:
    entry = ""
    label: dict[str, Any] | None = None

    def walk(obj: dict[str, Any]) -> None:
        nonlocal entry, label
        role = _role(obj)
        name = (_name(obj) or "").lower()
        if role in {"textfield", "textarea"}:
            entry = str(obj.get("value") or "")
        if role == "text" and name == "idle":
            label = obj
        for child in _children(obj):
            walk(child)

    walk(root)
    if label is not None:
        label["name"] = entry.strip() or "sceneuse ios ok"


def load_fixture(path: str) -> Snap:
    root = json.loads(Path(path).read_text(encoding="utf-8"))
    return snapshot_tree(root, fixture=True)
