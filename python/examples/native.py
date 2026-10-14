"""Drive Notes (native AX), not a browser fixture.

Creates a new note titled/bodied with a marker. Does not delete it.
Refuses to type into a textarea that already has someone else's content.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

MARKER = "sceneuse native ok"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sceneuse.client import Client, SceneuseError  # noqa: E402


def activate_notes() -> None:
    subprocess.run(["open", "-a", "Notes"], check=False)
    subprocess.run(
        ["osascript", "-e", 'tell application "Notes" to activate'],
        check=False,
        capture_output=True,
    )


def pick_textarea(scene) -> dict | None:
    for n in scene.find(role="textarea"):
        val = (n.get("value") or "").strip().lower()
        if not val or val in {"new note", marker_l()}:
            return n
        if "evangelion" in val:
            continue
        if len(val) > 40:
            continue
        if val.startswith(marker_l()):
            return n
    empty = [n for n in scene.find(role="textarea") if not (n.get("value") or "").strip()]
    return empty[0] if empty else None


def marker_l() -> str:
    return MARKER.lower()


def main() -> int:
    activate_notes()
    time.sleep(0.6)
    try:
        with Client() as c:
            c.subscribe(tiles=False)
            scene = c.wait(lambda s: (s.focus.get("app") or "") == "Notes", timeout=12)
            print("--- notes ---")
            print(f"focus: {scene.focus}")

            cont = scene.find(role="button", name="Continue")
            if cont:
                print(f"invoke Continue {cont[0]['id']}")
                c.invoke(cont[0]["id"])
                scene = c.wait(
                    lambda s: not s.find(role="button", name="Continue"),
                    timeout=8,
                )

            new_btn = scene.find(role="button", name="New Note")
            if new_btn and "disabled" not in (new_btn[0].get("states") or []):
                print(f"invoke New Note {new_btn[0]['id']}")
                c.invoke(new_btn[0]["id"])
            else:
                print("key cmd+n")
                c.key("cmd", "n")

            scene = c.wait(lambda s: pick_textarea(s) is not None, timeout=8)
            field = pick_textarea(scene)
            if field is None:
                print("no safe textarea (refusing to overwrite an existing note)", file=sys.stderr)
                print(scene.render(), file=sys.stderr)
                return 1
            print(f"set {field['id']} -> {MARKER!r}")
            try:
                c.set(field["id"], MARKER)
            except SceneuseError as e:
                print(f"set failed ({e}); not typing into an unknown field", file=sys.stderr)
                return 1

            result = c.wait(lambda s: s.mentions(MARKER), timeout=10)
            print("--- after ---")
            # Don't dump the whole sidebar (other notes). Show the editor + marker hits.
            hits = [n for n in result.nodes if MARKER.lower() in f"{n.get('name') or ''} {n.get('value') or ''}".lower()]
            print(f"focus: {result.focus}")
            for n in hits[:8]:
                print(f"  [{n.get('id')}] {n.get('role')} value={n.get('value')!r}")
            print(f"ok: native scene mentions {MARKER!r}")
            print("delete the new Notes item if you do not want it")
            return 0
    except (ConnectionError, FileNotFoundError, OSError) as e:
        print(f"native failed to connect: {e}", file=sys.stderr)
        print("start the daemon: make daemon", file=sys.stderr)
        return 1
    except (TimeoutError, SceneuseError, RuntimeError) as e:
        print(f"native failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
