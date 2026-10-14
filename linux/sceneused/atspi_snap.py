"""AT-SPI snapshot → scene windows/nodes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .roles import INTERACTIVE, normalize_action, normalize_role

try:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    HAS_ATSPI = True
except Exception:  # noqa: BLE001 — sandbox may lack GI
    Atspi = None  # type: ignore[assignment]
    HAS_ATSPI = False


@dataclass
class Snap:
    windows: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    focus: dict[str, Any] = field(default_factory=dict)
    observe: dict[str, Any] = field(default_factory=dict)
    node_refs: dict[str, Any] = field(default_factory=dict)
    accessibility: bool = False


def accessibility_ok() -> bool:
    if not HAS_ATSPI:
        return False
    try:
        Atspi.init()
        desktop = Atspi.get_desktop(0)
        return desktop is not None and desktop.get_child_count() >= 0
    except Exception:  # noqa: BLE001
        return False


def _name(acc: Any) -> str | None:
    try:
        n = acc.get_name()
        return n or None
    except Exception:  # noqa: BLE001
        return None


def _role(acc: Any) -> str:
    try:
        r = acc.get_role_name()
        role = normalize_role(r)
    except Exception:  # noqa: BLE001
        return "unknown"
    # Gtk.Entry often reports AT-SPI role "text" → textarea; prefer textfield when single-line.
    if role == "textarea":
        try:
            st = acc.get_state_set()
            single = getattr(Atspi.StateType, "STATE_SINGLE_LINE", None)
            multi = getattr(Atspi.StateType, "STATE_MULTI_LINE", None)
            if st is not None and single is not None and st.contains(single):
                return "textfield"
            if st is not None and multi is not None and st.contains(multi):
                return "textarea"
            return "textfield"
        except Exception:  # noqa: BLE001
            return "textfield"
    return role


def _states(acc: Any) -> list[str]:
    out: list[str] = []
    try:
        st = acc.get_state_set()
        if st is None:
            return out
        mapping = [
            ("STATE_ENABLED", "enabled"),
            ("STATE_FOCUSABLE", "focusable"),
            ("STATE_FOCUSED", "focused"),
            ("STATE_CHECKED", "checked"),
            ("STATE_SELECTED", "selected"),
            ("STATE_EDITABLE", "editable"),
            ("STATE_VISIBLE", "visible"),
            ("STATE_SHOWING", "showing"),
            ("STATE_SENSITIVE", "enabled"),
        ]
        for attr, token in mapping:
            enum = getattr(Atspi.StateType, attr, None)
            if enum is not None and st.contains(enum):
                if token not in out:
                    out.append(token)
    except Exception:  # noqa: BLE001
        pass
    return out


def _actions(acc: Any) -> list[str]:
    out: list[str] = []
    try:
        ifaces = acc.get_interfaces() or []
        if "Action" not in ifaces and "action" not in [i.lower() for i in ifaces]:
            return out
    except Exception:  # noqa: BLE001
        pass
    try:
        n = acc.get_n_actions()
        for i in range(n):
            name = acc.get_action_name(i)
            if name:
                out.append(normalize_action(name))
    except Exception:  # noqa: BLE001
        pass
    seen: set[str] = set()
    uniq: list[str] = []
    for a in out:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq


def _bounds(acc: Any) -> dict[str, int] | None:
    try:
        ifaces = acc.get_interfaces() or []
        if "Component" not in ifaces and "component" not in [i.lower() for i in ifaces]:
            return None
    except Exception:  # noqa: BLE001
        pass
    try:
        # ATSPI_COORD_TYPE_SCREEN = 0
        ext = acc.get_extents(0)
        if ext is None:
            return None
        w, h = int(ext.width), int(ext.height)
        if w <= 0 or h <= 0:
            return None
        return {"x": int(ext.x), "y": int(ext.y), "w": w, "h": h}
    except Exception:  # noqa: BLE001
        return None


def _value(acc: Any) -> str | None:
    try:
        t = Atspi.Text.get_text(acc, 0, -1)
        if t:
            return t
    except Exception:  # noqa: BLE001
        pass
    try:
        text = acc.get_text(0, -1)
        if text:
            return text
    except Exception:  # noqa: BLE001
        pass
    try:
        iface = acc.get_text_iface()
        if iface is not None:
            t = iface.get_text(0, -1)
            if t:
                return t
    except Exception:  # noqa: BLE001
        pass
    return None


def _app_name(app: Any) -> str:
    return _name(app) or "unknown"


def _pid(app: Any) -> int:
    try:
        return int(app.get_process_id())
    except Exception:  # noqa: BLE001
        return 0


def snapshot(
    *,
    observe_window: str | None = None,
    observe_app: str | None = None,
    max_nodes: int = 400,
) -> Snap:
    snap = Snap()
    if not HAS_ATSPI:
        return snap
    try:
        Atspi.init()
        desktop = Atspi.get_desktop(0)
    except Exception:  # noqa: BLE001
        return snap

    snap.accessibility = True
    apps: list[Any] = []
    try:
        n = desktop.get_child_count()
        for i in range(n):
            child = desktop.get_child_at_index(i)
            if child is not None:
                apps.append(child)
    except Exception:  # noqa: BLE001
        return snap

    windows: list[dict[str, Any]] = []
    by_app: dict[str, Any] = {}
    for app in apps:
        name = _app_name(app)
        pid = _pid(app)
        wid = f"w:{pid}" if pid else f"w:{id(app)}"
        by_app[name.lower()] = app
        bounds = _bounds(app) or {"x": 0, "y": 0, "w": 1280, "h": 720}
        windows.append(
            {
                "id": wid,
                "app": name,
                "title": name,
                "pid": pid,
                "bounds": bounds,
                "focused": False,
            }
        )

    # Prefer observe handle, else focused app (or fixture).
    chosen: Any | None = None
    chosen_win: dict[str, Any] | None = None

    if observe_window:
        for w in windows:
            if w["id"] == observe_window:
                chosen_win = w
                for app in apps:
                    if (f"w:{_pid(app)}" if _pid(app) else f"w:{id(app)}") == observe_window:
                        chosen = app
                        break
                break
    if chosen is None and observe_app:
        key = observe_app.lower()
        for app in apps:
            if key in _app_name(app).lower():
                chosen = app
                break
        for w in windows:
            if key in (w.get("app") or "").lower():
                chosen_win = w
                break

    if chosen is None:
        # Prefer fixture, else first app with children.
        for app in apps:
            if "fixture" in _app_name(app).lower() or "sceneuse" in _app_name(app).lower():
                chosen = app
                break
        if chosen is None:
            for app in apps:
                try:
                    if app.get_child_count() > 0:
                        chosen = app
                        break
                except Exception:  # noqa: BLE001
                    continue
        if chosen is None and apps:
            chosen = apps[0]

    if chosen is not None and chosen_win is None:
        pid = _pid(chosen)
        wid = f"w:{pid}" if pid else f"w:{id(chosen)}"
        for w in windows:
            if w["id"] == wid:
                chosen_win = w
                break
        if chosen_win is None:
            chosen_win = {
                "id": wid,
                "app": _app_name(chosen),
                "title": _app_name(chosen),
                "pid": pid,
                "bounds": _bounds(chosen) or {"x": 0, "y": 0, "w": 420, "h": 220},
                "focused": True,
            }
            windows.append(chosen_win)

    if chosen_win is not None:
        chosen_win["focused"] = True
        snap.focus = {
            "app": chosen_win.get("app"),
            "pid": chosen_win.get("pid"),
            "window": chosen_win.get("id"),
        }
        snap.observe = dict(snap.focus)

    # Synthetic single window if listing empty but we somehow have chosen.
    if not windows and chosen is not None:
        windows.append(chosen_win or {"id": "w:0", "app": "unknown", "pid": 0, "bounds": {"x": 0, "y": 0, "w": 1280, "h": 720}, "focused": True})

    snap.windows = windows

    if chosen is None:
        return snap

    wid = (chosen_win or {}).get("id") or "w:0"
    nodes: list[dict[str, Any]] = []
    refs: dict[str, Any] = {}
    counter = [0]

    def walk(acc: Any, depth: int) -> None:
        if len(nodes) >= max_nodes or depth > 24:
            return
        role = _role(acc)
        name = _name(acc)
        states = _states(acc)
        actions = _actions(acc)
        bounds = _bounds(acc)
        # Always snapshot text for fields/labels so set() round-trips show up.
        value = None
        if role in {"textfield", "textarea", "text"} or "editable" in states:
            value = _value(acc)

        keep = (
            role in INTERACTIVE
            or role in {"window", "dialog", "web", "text", "heading"}
            or (name and role not in {"group", "unknown"})
            or depth == 0
        )
        if keep:
            nid = f"n{counter[0]}"
            counter[0] += 1
            node: dict[str, Any] = {
                "id": nid,
                "role": role,
                "window": wid,
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
            if "focused" in states:
                node["tags"].append("focus")
            nodes.append(node)
            refs[nid] = acc

        try:
            count = acc.get_child_count()
        except Exception:  # noqa: BLE001
            return
        for i in range(count):
            try:
                child = acc.get_child_at_index(i)
            except Exception:  # noqa: BLE001
                continue
            if child is not None:
                walk(child, depth + 1)

    walk(chosen, 0)
    snap.nodes = nodes
    snap.node_refs = refs
    return snap


def do_invoke(acc: Any, action: str | None) -> None:
    want = normalize_action(action or "press")
    n = acc.get_n_actions()
    idx = 0
    for i in range(n):
        if normalize_action(acc.get_action_name(i)) == want:
            idx = i
            break
    if n <= 0:
        raise RuntimeError("no actions on node")
    ok = acc.do_action(idx)
    if not ok:
        raise RuntimeError(f"do_action({idx}) failed")


def do_set(acc: Any, value: str) -> None:
    # GI: EditableText.set_text_contents(accessible, string)
    try:
        Atspi.EditableText.set_text_contents(acc, value)
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        et = acc.get_editable_text_iface()
        if et is not None:
            et.set_text_contents(value)
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        if hasattr(acc, "set_text_contents"):
            acc.set_text_contents(value)
            return
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError("node is not editable")


def now_ms() -> int:
    return int(time.time() * 1000)
