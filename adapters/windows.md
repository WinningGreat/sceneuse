# Windows adapter contract

v1 does not ship a Windows daemon. This is the mapping an adapter must implement so it speaks the same [Scene / Act protocol](../spec/scene.md).

Prefer **Microsoft UFO²** or **Terminator** if you need a Windows *agent loop* today. A sceneuse adapter should expose the observation, not reimplement their planner.

## Capture (damage + tiles)

Use **DXGI Desktop Duplication** (`IDXGIOutputDuplication`), not GDI `BitBlt` screenshots.

| Scene field | Source |
| --- | --- |
| `damage[]` | `GetFrameDirtyRects` unioned with destinations from `GetFrameMoveRects` |
| move handling | apply move rects first (copy within the accumulated image), then dirty rects |
| `tiles[]` | encode a dirty rect only when it is not covered by a usable UIA node; skip rects ≥ 40% of the display; JPEG long side ≤ 512 |
| `cursor` | `IDXGIOutputDuplication::GetFramePointerShape` + pointer position in `DXGI_OUTDUPL_FRAME_INFO` |
| `displays[]` | `IDXGIOutput` + DPI (`GetDpiForMonitor`); bounds in logical points, origin top-left of the primary display |

Do **not** call duplication setup on every frame. Create the output duplication once per display; recreate only on `DXGI_ERROR_ACCESS_LOST` (mode change, UAC, exclusive fullscreen).

Windows Graphics Capture is acceptable for window-scoped tiles; DXGI remains the right source for desktop-wide dirty metadata.

## Windows (identity)

| Scene field | Source |
| --- | --- |
| `windows[]` | `EnumWindows` + DWM (`DwmGetWindowAttribute` for bounds, cloaked state) |
| `id` | `w:{HWND}` hex |
| `z` | front-to-back order from `GetWindow(GW_HWNDNEXT)` starting at the foreground window |
| `focused` | `GetForegroundWindow` |
| `occluded` | fully contained by a higher window’s bounds |
| `pid` / `app` / `bundle` | `GetWindowThreadProcessId`, process image name |

## Nodes (structure)

| Scene field | Source |
| --- | --- |
| `nodes[]` | UI Automation (`IUIAutomation`) tree of the focused window, pruned like macOS (~200 nodes, interactive + named) |
| `id` | `n{i}` stable until the next `nodes` payload |
| `role` | map `ControlType` to the spec tokens (`button`, `textfield`, …) |
| `actions` | available patterns: Invoke → `press`, Value → implied by `set`, Toggle, ExpandCollapse, Range |
| `bounds` | `IUIAutomationElement::CurrentBoundingRectangle`, converted to logical top-left-of-primary |

If UIA is empty (custom-drawn / game), leave `nodes` empty and allow tiles on remaining dirty rects.

## Act

| op | Implementation |
| --- | --- |
| `invoke` | `IInvokeProvider::Invoke` (or Toggle/Expand as mapped) |
| `set` | `IValueProvider::SetValue` after `SetFocus` |
| `hit` | `SendInput` at window-local point converted to screen |
| `key` | `SendInput` virtual keys |
| `scroll` / `drag` | `SendInput` wheel / mouse |

Missing UIA: `invoke` / `set` → `permission_denied` or `not_found`. Geometry ops still work.

## Permissions / session

Desktop duplication fails in Session 0 and some full-screen exclusive games. Surface that as `permissions.screen_recording: false` with empty `damage` / `tiles`. UIA may still populate `nodes`.

Socket: named pipe `\\.\pipe\sceneuse` is an acceptable Windows transport **if** the envelope stays NDJSON. Document the path in `status.result.socket`.
