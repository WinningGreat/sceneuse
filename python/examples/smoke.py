"""Print one scene. Used by `python -m sceneuse smoke`."""

from sceneuse.cli import _smoke

if __name__ == "__main__":
    raise SystemExit(_smoke(None))
