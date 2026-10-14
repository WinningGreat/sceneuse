from __future__ import annotations

import unittest
from pathlib import Path

from sceneused.roles import normalize_role
from sceneused.uia_snap import apply_mark, apply_set, load_fixture, snapshot_xml

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "fixture.xml"


class RoleTests(unittest.TestCase):
    def test_button_and_edit(self) -> None:
        self.assertEqual(normalize_role("android.widget.Button"), "button")
        self.assertEqual(normalize_role("android.widget.EditText"), "textfield")
        self.assertEqual(normalize_role("androidx.recyclerview.widget.RecyclerView"), "list")


class DumpTests(unittest.TestCase):
    def test_fixture_nodes(self) -> None:
        snap = load_fixture(str(FIXTURE))
        self.assertTrue(snap.accessibility)
        roles = {n["id"]: n for n in snap.nodes}
        self.assertTrue(any(n.get("role") == "textfield" and n.get("name") == "Fixture entry" for n in snap.nodes))
        self.assertTrue(any(n.get("role") == "button" and n.get("name") == "Mark" for n in snap.nodes))
        self.assertTrue(any(n.get("role") == "text" and n.get("name") == "idle" for n in snap.nodes))
        entry = next(n for n in snap.nodes if n.get("role") == "textfield")
        self.assertIn("focus", entry.get("tags") or [])
        self.assertIn("target", entry.get("tags") or [])
        self.assertEqual(entry["bounds"]["x"], 16.0)  # 48 / 3
        del roles

    def test_set_and_mark(self) -> None:
        snap = load_fixture(str(FIXTURE))
        entry_el = snap.node_refs[next(n["id"] for n in snap.nodes if n.get("role") == "textfield")]
        apply_set(entry_el, "sceneuse android ok")
        apply_mark(snap.root)  # type: ignore[arg-type]
        import xml.etree.ElementTree as ET

        xml = ET.tostring(snap.root, encoding="unicode")  # type: ignore[arg-type]
        again = snapshot_xml(xml, scale=3, fixture=True, package="dev.sceneuse.fixture")
        self.assertTrue(
            any("sceneuse android ok" in ((n.get("name") or "") + (n.get("value") or "")) for n in again.nodes)
        )


if __name__ == "__main__":
    unittest.main()
