from __future__ import annotations

import unittest
from pathlib import Path

from sceneused.axp import parse_iosef_text, unwrap_axp
from sceneused.roles import normalize_role
from sceneused.tree import apply_mark, apply_set, load_fixture, snapshot_tree

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "fixture.json"


class RoleTests(unittest.TestCase):
    def test_ax_roles(self) -> None:
        self.assertEqual(normalize_role("AXButton"), "button")
        self.assertEqual(normalize_role("AXTextField"), "textfield")
        self.assertEqual(normalize_role("AXStaticText"), "text")


class TreeTests(unittest.TestCase):
    def test_fixture_nodes(self) -> None:
        snap = load_fixture(str(FIXTURE))
        self.assertTrue(snap.accessibility)
        self.assertTrue(any(n.get("role") == "textfield" and n.get("name") == "Fixture entry" for n in snap.nodes))
        self.assertTrue(any(n.get("role") == "button" and n.get("name") == "Mark" for n in snap.nodes))
        entry = next(n for n in snap.nodes if n.get("role") == "textfield")
        self.assertIn("target", entry.get("tags") or [])

    def test_set_and_mark(self) -> None:
        snap = load_fixture(str(FIXTURE))
        entry = snap.node_refs[next(n["id"] for n in snap.nodes if n.get("role") == "textfield")]
        apply_set(entry, "sceneuse ios ok")
        apply_mark(snap.root)  # type: ignore[arg-type]
        again = snapshot_tree(snap.root, fixture=True)  # type: ignore[arg-type]
        self.assertTrue(
            any("sceneuse ios ok" in ((n.get("name") or "") + (n.get("value") or "")) for n in again.nodes)
        )


class IosefTextTests(unittest.TestCase):
    SAMPLE = """\
AXApplication "Settings" (201±201, 437±437)
  AXHeading "Settings" (83±67, 140±20) [header]
  AXGroup (201±201, 437±437)
    AXButton "General" (201±185, 406±26)
    AXButton "Accessibility" (201±185, 458±26)
  AXTextField (201±168, 822±19) value="Search" [searchField]
"""

    def test_parse_settings_tree(self) -> None:
        root = parse_iosef_text(self.SAMPLE)
        assert root is not None
        snap = snapshot_tree(root, bundle="com.apple.Preferences", app="Settings")
        names = [n.get("name") for n in snap.nodes]
        self.assertIn("General", names)
        self.assertIn("Accessibility", names)
        general = next(n for n in snap.nodes if n.get("name") == "General")
        self.assertEqual(general["role"], "button")
        b = general["bounds"]
        self.assertAlmostEqual(b["x"], 16.0)
        self.assertAlmostEqual(b["y"], 380.0)
        self.assertAlmostEqual(b["w"], 370.0)
        search = next(n for n in snap.nodes if n.get("role") == "textfield")
        self.assertEqual(search.get("value"), "Search")

    def test_multiline_tab_name(self) -> None:
        text = """\
AXApplication "PairRide" (201±201, 437±437)
  AXButton "Home
Tab 1 of 3" (67±67, 800±40) [selected]
  AXButton "Account
Tab 3 of 3" (335±67, 800±40)
"""
        root = parse_iosef_text(text)
        assert root is not None
        names = [c.get("name") for c in root.get("children") or []]
        self.assertIn("Home Tab 1 of 3", names)
        self.assertIn("Account Tab 3 of 3", names)

    def test_unwrap_mcp_envelope(self) -> None:
        env = {"content": [{"type": "text", "text": self.SAMPLE}]}
        root = unwrap_axp(env)
        assert root is not None
        self.assertEqual(root.get("name"), "Settings")


if __name__ == "__main__":
    unittest.main()
