# Linux adapter contract

Sandbox daemon: [`linux/`](../linux/) (Docker + Xvfb + AT-SPI). Capture via PipeWire/portal is still the production target below; the sandbox keeps `screen_recording: false` and implements nodes + `invoke` / `set`.

This is the mapping a full adapter must implement so it speaks the same [Scene / Act protocol](../spec/scene.md).

Daytona’s AT-SPI endpoints are a useful reference for `nodes` / `invoke`, but they sit beside screenshot APIs. A sceneuse adapter must emit **one** Scene stream.

## Capture (damage + tiles)

Wayland: **xdg-desktop-portal ScreenCast** + **PipeWire**.

| Scene field | Source |
| --- | --- |
| `damage[]` | PipeWire buffer metadata `SPA_META_VideoDamage` (`struct spa_meta_region`) |
| `tiles[]` | same coverage rules as macOS: skip if a usable AT-SPI node covers the rect; skip ≥ 40% of the display; JPEG long side ≤ 512 |
| `cursor` | portal cursor metadata when negotiated; else the compositor’s pointer position if a privileged protocol exists |
| `displays[]` | portal / RandR / wl output logical size and scale |

X11 fallback (Xorg only): MIT-SHM + XDamage. Do not use `XGetImage` of the full root as the primary observation.

Negotiate `SPA_PARAM_Meta` for `SPA_META_VideoDamage` at stream connect. If the compositor omits damage, treat the whole buffer as one dirty rect **but still do not send a full-display JPEG** (drop that tile; rely on AT-SPI).

## Windows (identity)

Wayland does not allow global window enumeration by design.

| Scene field | Source |
| --- | --- |
| `windows[]` | `wlr-foreign-toplevel-management` (wlroots) **or** `org.freedesktop.impl.portal.Foreign` / ext-foreign-toplevel where available |
| GNOME | `org.gnome.Shell.Introspect` is acceptable with a documented permission story |
| `id` | compositor toplevel handle, prefixed `w:` |
| `focused` | activated toplevel |
| `bounds` | protocol geometry if exposed; otherwise AT-SPI extents |

If toplevel listing is denied, emit a single synthetic window for the focused AT-SPI application so `hit` still has a `window` id.

## Nodes (structure)

| Scene field | Source |
| --- | --- |
| `nodes[]` | AT-SPI2 over D-Bus (`org.a11y.atspi`), focused application / window |
| `id` | `n{i}` until the next `nodes` payload |
| `role` | map AT-SPI `Role` to spec tokens |
| `actions` | `GetActions` → `press` / `show_menu` / … |
| `bounds` | `GetExtents` in desktop coords, origin top-left of the primary logical display |

Chromium often needs `--force-renderer-accessibility`. Document that; do not scrape the DOM from the adapter.

Supervise `at-spi-bus-launcher` in headless/CI images.

## Act

| op | Implementation |
| --- | --- |
| `invoke` | AT-SPI `DoAction` |
| `set` | AT-SPI text / value interfaces |
| `hit` / `key` / `scroll` / `drag` | **uinput** or portal RemoteDesktop (preferred on locked-down Wayland) |

Do not assume XTEST on Wayland.

## Permissions

Portal screen-cast is per-session and user-gated. Map denial to `permissions.screen_recording: false`. Map a missing a11y bus to `permissions.accessibility: false`.

Socket: `$XDG_RUNTIME_DIR/sceneuse.sock` (fallback `/tmp/sceneuse.sock`).
