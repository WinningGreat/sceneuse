# Linux Docker sandbox

AT-SPI-first `sceneused` for CI / local Docker. PipeWire + portal capture is **not** implemented here — `permissions.screen_recording` stays `false`. Geometric `hit` / `key` / `scroll` / `drag` return `permission_denied` until uinput/RemoteDesktop lands.

## Quick test

From repo root (Docker required):

```sh
make linux-image
make linux-smoke
```

`linux-smoke` boots Xvfb + D-Bus + AT-SPI + a GTK fixture, runs the daemon, then `sceneuse smoke` + set/invoke loop.

Interactive shell in the same environment:

```sh
make linux-shell
# inside: python3 -m sceneused &
#         PYTHONPATH=/app/python python3 -m sceneuse scene --no-tiles
```

Socket: `$XDG_RUNTIME_DIR/sceneuse.sock` (default `/tmp/runtime/sceneuse.sock` in the image).
