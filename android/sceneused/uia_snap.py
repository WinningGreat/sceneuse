"""uiautomator dump XML → scene windows/nodes. Fixture mode mutates the tree in memory."""

from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .roles import INTERACTIVE, normalize_role

_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


@dataclass
class Snap:
    windows: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    focus: dict[str, Any] = field(default_factory=dict)
    observe: dict[str, Any] = field(default_factory=dict)
    node_refs: dict[str, ET.Element] = field(default_factory=dict)
    accessibility: bool = False
    display: dict[str, Any] = field(default_factory=dict)
    scale: float = 1.0
    root: ET.Element | None = None
    package: str = "unknown"
    fixture: bool = False


def now() -> float:
    return time.time()


def parse_bounds(raw: str | None, scale: float) -> dict[str, float] | None:
    if not raw:
        return None
    m = _BOUNDS.search(raw)
    if not m:
        return None
    l, t, r, b = (int(m.group(i)) for i in range(1, 5))
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return None
    s = scale if scale > 0 else 1.0
    return {"x": l / s, "y": t / s, "w": w / s, "h": h / s}


def _truthy(v: str | None) -> bool:
    return (v or "").lower() == "true"


def _attr(el: ET.Element, *names: str) -> str:
    for n in names:
        val = el.attrib.get(n)
        if val:
            return val
    return ""


def flatten(
    root: ET.Element,
    *,
    window_id: str,
    scale: float,
    max_nodes: int = 200,
    max_depth: int = 24,
) -> tuple[list[dict[str, Any]], dict[str, ET.Element], int]:
    nodes: list[dict[str, Any]] = []
    refs: dict[str, ET.Element] = {}
    total = [0]

    def walk(el: ET.Element, depth: int, parent: str | None) -> None:
        if el.tag != "node" and el.tag != "hierarchy":
            for child in list(el):
                walk(child, depth, parent)
            return
        if el.tag == "hierarchy":
            for child in list(el):
                walk(child, depth, parent)
            return
        total[0] += 1
        if len(nodes) >= max_nodes or depth > max_depth:
            return
        cls = _attr(el, "class")
        role = normalize_role(cls)
        desc = _attr(el, "content-desc", "contentDescription")
        text = _attr(el, "text")
        rid = _attr(el, "resource-id", "resourceId")
        clickable = _truthy(_attr(el, "clickable"))
        long_click = _truthy(_attr(el, "long-clickable", "longClickable"))
        enabled = _attr(el, "enabled") != "false"
        focused = _truthy(_attr(el, "focused"))
        checked = _truthy(_attr(el, "checked"))
        selected = _truthy(_attr(el, "selected"))
        editable = role in {"textfield", "textarea"} or "edit" in cls.lower()
        password = _truthy(_attr(el, "password"))
        bounds = parse_bounds(_attr(el, "bounds"), scale)

        name = desc or (text if not editable else "") or (rid.rsplit("/", 1)[-1] if rid else "")
        name = name or None
        value = text if editable else None

        states: list[str] = []
        if enabled:
            states.append("enabled")
        if clickable or editable:
            states.append("focusable")
        if focused:
            states.append("focused")
        if checked:
            states.append("checked")
        if selected:
            states.append("selected")
        if editable:
            states.append("editable")
        if password:
            states.append("password")

        actions: list[str] = []
        if clickable or role in INTERACTIVE:
            actions.append("press")
        if long_click:
            actions.append("show_menu")

        keep = (
            role in INTERACTIVE
            or role in {"window", "dialog", "web", "text", "heading"}
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
            if value is not None:
                node["value"] = value
            if bounds:
                node["bounds"] = bounds
            if parent:
                node["parent"] = parent
            if focused:
                node["tags"].append("focus")
            nodes.append(node)
            refs[nid] = el

        for child in list(el):
            walk(child, depth + 1, nid or parent)

    start = root
    if root.tag == "hierarchy":
        kids = list(root)
        start = kids[0] if kids else root
    walk(start, 0, None)
    return nodes, refs, total[0]


def _window(
    *,
    wid: str,
    app: str,
    bundle: str | None,
    title: str | None,
    bounds: dict[str, float],
    pid: int = 0,
) -> dict[str, Any]:
    return {
        "id": wid,
        "pid": pid,
        "app": app,
        "bundle": bundle,
        "title": title,
        "bounds": bounds,
        "z": 0,
        "focused": True,
        "on_screen": True,
        "occluded": False,
    }


def snapshot_xml(
    xml_text: str,
    *,
    scale: float = 1.0,
    display_w: float = 360,
    display_h: float = 800,
    package: str = "dev.sceneuse.fixture",
    title: str | None = None,
    pid: int = 0,
    fixture: bool = False,
    observe_app: str | None = None,
) -> Snap:
    snap = Snap(scale=scale, fixture=fixture, package=package)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return snap
    snap.root = root
    snap.accessibility = True
    dw, dh = display_w, display_h
    # Prefer dump root bounds when present.
    first = None
    if root.tag == "hierarchy":
        kids = [c for c in root if c.tag == "node"]
        first = kids[0] if kids else None
    elif root.tag == "node":
        first = root
    if first is not None:
        b = parse_bounds(_attr(first, "bounds"), scale)
        if b and b["w"] > 0 and b["h"] > 0:
            dw, dh = b["w"], b["h"]
        pkg = _attr(first, "package")
        if pkg:
            package = pkg
            snap.package = pkg
    if observe_app and observe_app.lower() not in package.lower() and observe_app.lower() not in (title or "").lower():
        # still emit the dump; target matching is best-effort for a single activity
        pass
    wid = f"w:{package}"
    bounds = {"x": 0.0, "y": 0.0, "w": dw, "h": dh}
    snap.display = {"id": "d0", "bounds": dict(bounds), "scale": scale}
    win = _window(
        wid=wid,
        app=package.rsplit(".", 1)[-1],
        bundle=package,
        title=title or package,
        bounds=bounds,
        pid=pid,
    )
    snap.windows = [win]
    snap.focus = {"window": wid, "app": win["app"], "pid": pid}
    snap.observe = dict(snap.focus)
    nodes, refs, count = flatten(root, window_id=wid, scale=scale)
    snap.nodes = nodes
    snap.node_refs = refs
    snap.display["bounds"] = bounds
    # tag one target: focused field, else first textfield, else first button
    tagged = False
    for n in nodes:
        if "focus" in (n.get("tags") or []):
            n["tags"].append("target")
            tagged = True
            break
    if not tagged:
        for want in ("textfield", "textarea", "button"):
            for n in nodes:
                if n.get("role") == want:
                    n.setdefault("tags", []).append("target")
                    tagged = True
                    break
            if tagged:
                break
    del count
    return snap


def apply_set(el: ET.Element, value: str) -> None:
    el.set("text", value)


def apply_mark(root: ET.Element) -> None:
    """Fixture: copy EditText text onto the idle label (GTK-loop analog)."""
    entry_text = ""
    label = None
    for el in root.iter("node"):
        cls = (_attr(el, "class") or "").lower()
        name = _attr(el, "content-desc") or _attr(el, "text")
        if "edittext" in cls or normalize_role(_attr(el, "class")) == "textfield":
            entry_text = _attr(el, "text")
        if name.lower() == "idle" or (
            normalize_role(_attr(el, "class")) == "text" and _attr(el, "text").lower() in {"idle", ""}
        ):
            if name.lower() == "idle" or _attr(el, "text").lower() == "idle":
                label = el
    if label is None:
        texts = [
            el
            for el in root.iter("node")
            if normalize_role(_attr(el, "class")) == "text" and _attr(el, "content-desc").lower() != "fixture entry"
        ]
        label = texts[-1] if texts else None
    if label is not None:
        label.set("text", (entry_text.strip() or "sceneuse android ok"))


def load_fixture(path: str) -> Snap:
    xml_text = Path(path).read_text(encoding="utf-8")
    scale = float(os.environ.get("SCENEUSE_ANDROID_SCALE") or 3)
    return snapshot_xml(
        xml_text,
        scale=scale,
        display_w=360,
        display_h=800,
        package="dev.sceneuse.fixture",
        title="sceneuse-fixture",
        fixture=True,
    )
