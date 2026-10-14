"""Live: Settings on a booted iOS Simulator — scene, invoke General, read the result."""

from __future__ import annotations

import os
import sys
import time

from sceneuse.client import Client


def main() -> int:
    with Client() as c:
        st = c.status()
        print("status:", st)
        if st.get("adapter") != "ios":
            print("expected ios adapter", file=sys.stderr)
            return 1
        if not (st.get("permissions") or {}).get("accessibility"):
            print("accessibility false — need iosef/idb and a booted Simulator", file=sys.stderr)
            return 1
        c.act(op="raise", app="com.apple.Preferences")
        time.sleep(0.8)
        c.subscribe(tiles=False, app="Preferences")
        scene = c.wait(
            lambda s: any(
                n.get("role") == "button" and "general" in (n.get("name") or "").lower()
                for n in s.nodes
            ),
            timeout=20,
        )
        print("--- Settings ---")
        print(scene.render())
        general = next(
            n
            for n in scene.nodes
            if n.get("role") == "button" and "general" in (n.get("name") or "").lower()
        )
        c.invoke(general["id"])
        scene = c.wait(
            lambda s: any(
                "about" in (n.get("name") or "").lower()
                or (n.get("role") == "heading" and "general" in (n.get("name") or "").lower())
                or (n.get("role") == "button" and (n.get("name") or "").lower() in {"back", "settings"})
                for n in s.nodes
            ),
            timeout=15,
        )
        print("--- after General ---")
        print(scene.render())
        names = " ".join((n.get("name") or "") for n in scene.nodes)
        if "About" not in names and "General" not in names:
            print("did not land on General", file=sys.stderr)
            return 1
        print("ios simulator loop ok")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
