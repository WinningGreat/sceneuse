# Android adapter contract

Host-side daemon: [`android/`](../android/). Speaks the same [Scene / Act protocol](../spec/scene.md) over a Unix socket on the machine that has `adb`.

v1 is **nodes-first**, like the Linux AT-SPI sandbox. `uiautomator dump` is the tree; `input tap` / `input swipe` / `input text` are geometry. SurfaceFlinger damage + `screencap` tiles are the production capture target below; the sandbox keeps `screen_recording: false`.

Do not wrap Appium as the observation. One Scene stream.

## Capture (damage + tiles)

| Scene field | Source |
| --- | --- |
| `damage[]` | SurfaceFlinger / `dumpsys SurfaceFlinger --latency` is **not** a dirty-rect API. Leave `[]` until a buffer-queue damage source exists. |
| `tiles[]` | same coverage rules as macOS: skip if a usable node covers the rect; skip ≥ 40% of the display; JPEG long side ≤ 512. `adb exec-out screencap -p` is acceptable **only** to encode those leftover rects — never a full-screen JPEG as the primary observation |
| `cursor` | `{visible: false}`; last tap point if known |
| `displays[]` | `wm size` + `wm density`. Bounds in **logical points** (`px * 160 / density`), origin top-left of the screen. `scale` is `density / 160` |

## Windows (identity)

Android has activities, not overlapping desktop windows.

| Scene field | Source |
| --- | --- |
| `windows[]` | resumed activity from `dumpsys activity activities` / `dumpsys window` (`mCurrentFocus`). Optional extra window when the IME is shown (`dumpsys input_method` `mInputShown`) |
| `id` | `w:{package}` (task id if available) |
| `app` | package or launcher label |
| `bundle` | package name |
| `title` | activity class short name |
| `bounds` | the display (activity is full-screen) |
| `focused` | resumed activity |
| `pid` | `pidof {package}` |

If listing fails, emit a single synthetic window so `hit` still has a `window` id.

## Nodes (structure)

| Scene field | Source |
| --- | --- |
| `nodes[]` | `uiautomator dump` XML of the current window, pruned like macOS (~200 nodes, interactive + named) |
| `id` | `n{i}` until the next `nodes` payload |
| `role` | map `class` to spec tokens (`android.widget.Button` → `button`, `EditText` → `textfield`, …) |
| `name` | `content-desc`, else `text` for non-fields |
| `value` | `text` on editable fields |
| `actions` | `clickable` → `press`; `long-clickable` → `show_menu`; `scrollable` implied by `scroll` |
| `bounds` | dump `[l,t][r,b]` converted to logical points |

`uiautomator dump` is read-only. `invoke` / `set` are implemented with `input` (tap the node, then set text). A future on-device `AccessibilityService` can `performAction` directly — same protocol.

Secure windows (banking, DRM) dump empty; leave `nodes` empty and do not screenshot them.

## Act

| op | Implementation |
| --- | --- |
| `invoke` | `input tap` at the node center (`press`); long-press swipe-in-place for `show_menu` |
| `set` | tap the field, then clipboard paste or `input text` |
| `hit` | `input tap` (`left`), double-tap (`double`), long-press (`right`) |
| `drag` | `input swipe` |
| `scroll` | swipe from `point`; positive `dy` moves content down (finger moves down) |
| `key` | `input keyevent` / `input text`. Tokens: letters, `return`, `tab`, `space`, `escape`, `back`, `home`, `delete` |
| `raise` | `am start` / launcher monkey for `params.app` (package substring) |

## Permissions

`permissions.accessibility` is true when a dump succeeds. Map `adb` disconnected to `accessibility: false`.

`permissions.screen_recording` stays false until sparse `screencap` tiles ship.

Socket: `$SCENEUSE_SOCK` or `/tmp/sceneuse-android.sock` (does not steal the macOS `/tmp/sceneuse.sock`).

Serial: `$SCENEUSE_ANDROID_SERIAL` or `adb` default device.
