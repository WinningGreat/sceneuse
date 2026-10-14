"""set + invoke on the GTK fixture inside the Linux sandbox."""

from __future__ import annotations

import sys
import time

from sceneuse.client import Client


def main() -> int:
    with Client() as c:
        st = c.status()
        print("status:", st)
        if not (st.get("permissions") or {}).get("accessibility"):
            print("accessibility false", file=sys.stderr)
            return 1
        c.subscribe(tiles=False)
        scene = c.wait(
            lambda s: any(
                (n.get("name") or "").lower() == "mark" and n.get("role") == "button"
                for n in s.nodes
            ),
            timeout=12,
        )
        print(scene.render())
        entry = next(
            (
                n
                for n in scene.nodes
                if n.get("role") in {"textfield", "textarea"}
                and "fixture" in (n.get("name") or "").lower()
            ),
            None,
        )
        if entry is None:
            entry = next(
                (n for n in scene.nodes if n.get("role") in {"textfield", "textarea"}),
                None,
            )
        if entry is None:
            print("no textfield", file=sys.stderr)
            return 1
        c.set(entry["id"], "sceneuse linux ok")
        time.sleep(0.2)
        scene = c.next_scene(timeout=5)
        mark = next(
            (
                n
                for n in scene.nodes
                if n.get("role") == "button" and (n.get("name") or "").lower() == "mark"
            ),
            None,
        )
        if mark is None:
            print("no Mark button", file=sys.stderr)
            return 1
        c.invoke(mark["id"])
        scene = c.wait(
            lambda s: any(
                "sceneuse linux ok" in ((n.get("name") or "") + (n.get("value") or ""))
                for n in s.nodes
            ),
            timeout=8,
        )
        print("--- after invoke ---")
        print(scene.render())
        print("linux loop ok")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
