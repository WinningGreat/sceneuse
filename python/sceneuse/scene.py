from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _rect(d: dict[str, Any] | None) -> dict[str, float] | None:
    if not d:
        return None
    return {k: float(d[k]) for k in ("x", "y", "w", "h") if k in d}


@dataclass
class Scene:
    raw: dict[str, Any]
    displays: list[dict[str, Any]] = field(default_factory=list)
    windows: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    damage: list[dict[str, Any]] = field(default_factory=list)
    tiles: list[dict[str, Any]] = field(default_factory=list)
    cursor: dict[str, Any] = field(default_factory=dict)
    focus: dict[str, Any] = field(default_factory=dict)
    observe: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    t: float = 0.0
    kind: str = "full"
    node_count: int | None = None

    @classmethod
    def from_message(cls, msg: dict[str, Any], previous: "Scene | None" = None) -> "Scene":
        kind = msg.get("kind") or "full"
        base = previous.raw.copy() if previous and kind == "delta" else {}
        if previous and kind == "delta":
            merged = {**base, **{k: v for k, v in msg.items() if v is not None}}
            for key in ("displays", "windows", "nodes"):
                if key not in msg or msg[key] is None:
                    merged[key] = previous.raw.get(key, [])
            if "node_count" not in msg:
                merged["node_count"] = previous.node_count
        else:
            merged = dict(msg)
        return cls(
            raw=merged,
            displays=list(merged.get("displays") or []),
            windows=list(merged.get("windows") or []),
            nodes=list(merged.get("nodes") or []),
            damage=list(merged.get("damage") or []),
            tiles=list(merged.get("tiles") or []),
            cursor=dict(merged.get("cursor") or {}),
            focus=dict(merged.get("focus") or {}),
            observe=dict(merged.get("observe") or merged.get("focus") or {}),
            permissions=dict(merged.get("permissions") or {}),
            seq=int(merged.get("seq") or 0),
            t=float(merged.get("t") or 0.0),
            kind=str(merged.get("kind") or "full"),
            node_count=merged.get("node_count"),
        )

    def node(self, node_id: str) -> dict[str, Any] | None:
        for n in self.nodes:
            if n.get("id") == node_id:
                return n
        return None

    def window(self, window_id: str) -> dict[str, Any] | None:
        for w in self.windows:
            if w.get("id") == window_id:
                return w
        return None

    def find(
        self,
        *,
        role: str | None = None,
        name: str | None = None,
        value: str | None = None,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for n in self.nodes:
            if role and n.get("role") != role:
                continue
            if name and name.lower() not in str(n.get("name") or "").lower():
                continue
            if value and value.lower() not in str(n.get("value") or "").lower():
                continue
            out.append(n)
        return out

    def mentions(self, text: str) -> bool:
        t = text.lower()
        for n in self.nodes:
            blob = f"{n.get('name') or ''} {n.get('value') or ''}".lower()
            if t in blob:
                return True
        for w in self.windows:
            blob = f"{w.get('app') or ''} {w.get('title') or ''}".lower()
            if t in blob:
                return True
        focus = f"{self.focus.get('app') or ''} {self.focus.get('window') or ''}".lower()
        return t in focus

    def render(self) -> str:
        """Compact LLM-facing text. Never dumps tile base64."""
        lines: list[str] = []
        if self.displays:
            d0 = self.displays[0]
            b = d0.get("bounds") or {}
            scale = d0.get("scale") or 1
            lines.append(
                f"display {d0.get('id', '0')} {int(b.get('w', 0))}x{int(b.get('h', 0))} @{scale:g}x"
            )
        app = self.focus.get("app") or "?"
        pid = self.focus.get("pid")
        win = self.focus.get("window") or "?"
        pid_s = f"  pid={pid}" if pid is not None else ""
        lines.append(f"focus: {app}{pid_s}  win={win}")
        obs = self.observe or {}
        oapp = obs.get("app") or app
        owin = obs.get("window") or win
        if (oapp, owin) != (app, win):
            opid = obs.get("pid")
            opid_s = f"  pid={opid}" if opid is not None else ""
            lines.append(f"observe: {oapp}{opid_s}  win={owin}")
        else:
            lines.append(f"observe: {oapp}  win={owin}")
        if self.windows:
            lines.append("windows:")
            for w in self.windows[:12]:
                marks = []
                if w.get("focused"):
                    marks.append("front")
                if w.get("id") == owin:
                    marks.append("observe")
                hint = f"  ({', '.join(marks)})" if marks else ""
                title = w.get("title") or ""
                if len(title) > 40:
                    title = title[:37] + "..."
                title_s = f' "{title}"' if title else ""
                lines.append(f"  [{w.get('id')}] {w.get('app') or '?'}{title_s}{hint}")
            extra_w = len(self.windows) - 12
            if extra_w > 0:
                lines.append(f"  … {extra_w} more")
        n_damage = len(self.damage)
        lines.append(f"damage: {n_damage} rect{'s' if n_damage != 1 else ''}")
        perms = self.permissions
        missing = [k for k, v in perms.items() if v is False]
        if missing:
            lines.append("permissions missing: " + ", ".join(missing))

        def line_for(n: dict[str, Any]) -> str | None:
            role = n.get("role") or "unknown"
            if role in {"group", "unknown"} and not n.get("name"):
                return None
            nid = n.get("id")
            name = n.get("name")
            value = n.get("value")
            tags = [t for t in (n.get("tags") or []) if t]
            extra = ""
            if name:
                extra += f' "{name}"'
            if value not in (None, ""):
                extra += f" value={value!r}"
            mark = "*" if "target" in tags else " "
            hint = f"  ({', '.join(tags)})" if tags else ""
            return f"  {mark}[{nid}] {role}{extra}{hint}"

        important = [n for n in self.nodes if n.get("tags")]
        important.sort(key=lambda n: (
            0 if "target" in (n.get("tags") or []) else 1,
            0 if "focus" in (n.get("tags") or []) else 1,
            0 if "cursor" in (n.get("tags") or []) else 1,
            0 if "changed" in (n.get("tags") or []) else 1,
        ))
        primary = [
            n for n in important
            if set(n.get("tags") or []) & {"target", "focus", "cursor"}
        ]
        extra = [n for n in important if n not in primary]
        shown_imp = (primary + extra)[:8]
        if shown_imp:
            lines.append("important:")
            for n in shown_imp:
                rendered = line_for(n)
                if rendered:
                    lines.append(rendered)

        lines.append("nodes:")
        shown = 0
        for n in self.nodes:
            rendered = line_for(n)
            if not rendered:
                continue
            lines.append(rendered)
            shown += 1
            if shown >= 80:
                rest = len(self.nodes) - shown
                if rest > 0:
                    lines.append(f"  … {rest} more")
                break
        if shown == 0:
            lines.append("  (none)")
        n_tiles = len(self.tiles)
        lines.append("tiles: none" if n_tiles == 0 else f"tiles: {n_tiles}")
        return "\n".join(lines)
