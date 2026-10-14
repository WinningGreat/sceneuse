"""Minimal accessible GTK window for Linux sandbox loop tests."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


class Fixture(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="sceneuse-fixture")
        self.set_default_size(420, 220)
        self.connect("destroy", Gtk.main_quit)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(16)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("type here")
        self.entry.get_accessible().set_name("Fixture entry")

        self.label = Gtk.Label(label="idle")
        # Let AT-SPI use the label string as the name (updates on set_text).

        btn = Gtk.Button(label="Mark")
        btn.get_accessible().set_name("Mark")
        btn.connect("clicked", self._on_mark)

        box.pack_start(self.entry, False, False, 0)
        box.pack_start(btn, False, False, 0)
        box.pack_start(self.label, False, False, 0)
        self.add(box)
        self.show_all()

    def _on_mark(self, *_args: object) -> None:
        text = self.entry.get_text().strip() or "sceneuse linux ok"
        self.label.set_text(text)


def main() -> None:
    Fixture()
    Gtk.main()


if __name__ == "__main__":
    main()
