from __future__ import annotations

import argparse
import json
import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sceneuse", description="sceneuse compositor-scene client")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="daemon permissions and adapter")
    p_status.add_argument("--sock", default=None)

    p_scene = sub.add_parser("scene", help="print one compact scene")
    p_scene.add_argument("--sock", default=None)
    p_scene.add_argument("--json", action="store_true")
    p_scene.add_argument("--no-tiles", action="store_true")

    p_inv = sub.add_parser("invoke", help="invoke a node from the last snapshot after one scene")
    p_inv.add_argument("node")
    p_inv.add_argument("--action", default="press")
    p_inv.add_argument("--sock", default=None)

    sub.add_parser("inspector", help="open the local scene inspector")
    sub.add_parser("smoke", help="connect, print one scene, exit")
    sub.add_parser("mcp", help="stdio MCP server for agents")

    p_doc = sub.add_parser("doctor", help="check daemon, permissions, MCP config")
    p_doc.add_argument("--sock", default=None)
    p_doc.add_argument("--fix", action="store_true", help="restart Sceneused.app on macOS")
    p_doc.add_argument("--open-settings", action="store_true", help="open Privacy panes on macOS")

    args = parser.parse_args(argv)
    if args.cmd == "inspector":
        from .inspector import serve

        serve()
        return 0
    if args.cmd == "mcp":
        from .mcp_server import serve

        serve()
        return 0
    if args.cmd == "smoke":
        return _smoke(getattr(args, "sock", None))
    if args.cmd == "doctor":
        from .doctor import run_doctor

        return run_doctor(
            sock=getattr(args, "sock", None),
            fix=bool(getattr(args, "fix", False)),
            open_settings=bool(getattr(args, "open_settings", False)),
        )
    if args.cmd == "status":
        from .client import Client

        with Client(path=args.sock) as c:
            print(json.dumps(c.status(), indent=2))
        return 0
    if args.cmd == "scene":
        from .client import Client

        with Client(path=args.sock) as c:
            c.subscribe(tiles=not args.no_tiles)
            scene = c.next_scene(timeout=8)
            if args.json:
                out = dict(scene.raw)
                tiles = []
                for t in out.get("tiles") or []:
                    tiles.append({**t, "data": f"<{len(t.get('data') or '')} b64 chars>"})
                out["tiles"] = tiles
                print(json.dumps(out, indent=2))
            else:
                print(scene.render())
        return 0
    if args.cmd == "invoke":
        from .client import Client

        with Client(path=args.sock) as c:
            c.subscribe(tiles=False)
            c.next_scene(timeout=8)
            print(json.dumps(c.invoke(args.node, args.action), indent=2))
        return 0
    return 1


def _smoke(sock: str | None) -> int:
    from .client import Client, SceneuseError

    try:
        with Client(path=sock) as c:
            hello = c._hello or {}
            print(f"hello adapter={hello.get('adapter')} protocol={hello.get('protocol')}")
            print(json.dumps(c.status(), indent=2))
            c.subscribe(tiles=True)
            scene = c.next_scene(timeout=8)
            print(scene.render())
            buttons = scene.find(role="button")
            if buttons:
                print(f"smoke: {len(buttons)} buttons in tree (not invoking)")
            return 0
    except (ConnectionError, FileNotFoundError, OSError) as e:
        print(f"smoke failed to connect: {e}", file=sys.stderr)
        print("start the daemon: make daemon", file=sys.stderr)
        return 1
    except SceneuseError as e:
        print(f"smoke protocol error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
