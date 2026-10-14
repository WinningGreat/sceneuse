# iOS adapter contract

Host-side daemon: [`ios/`](../ios/). Speaks the same [Scene / Act protocol](../spec/scene.md) over a Unix socket on the Mac that owns Simulator / `devicectl`.

v1 targets the **iOS Simulator**. Physical devices need a signed XCUITest / Developer Disk Image companion and are out of this sandbox.

The production tree source is **AXP** (the VoiceOver hierarchy CoreSimulator already speaks — `idb`, `iosef`). Do not scrape the Simulator.app **Mac** AX tree: that is chrome (volume, toolbar), not the iOS app. Do not wrap Appium as the observation. One Scene stream.

## Capture (damage + tiles)

| Scene field | Source |
| --- | --- |
| `damage[]` | none in v1 (`simctl io` has screenshot/record, not dirty rects) |
| `tiles[]` | same coverage rules as macOS. `simctl io screenshot` only to encode leftover rects — never a full-screen JPEG as the primary observation |
| `cursor` | `{visible: false}` |
| `displays[]` | `simctl getenv SIMULATOR_MAINSCREEN_{WIDTH,HEIGHT,SCALE}` converted to logical points (`px / scale`) |

## Windows (identity)

One scene fills the display.

| Scene field | Source |
| --- | --- |
| `windows[]` | foreground app (SpringBoard or the launched bundle). `simctl listapps` + process list; `raise` / `target` switch by bundle substring |
| `id` | `w:{bundle}` |
| `app` | `CFBundleDisplayName` |
| `bundle` | `CFBundleIdentifier` |
| `bounds` | the display |
| `pid` | simulator-side pid when known, else `0` |

## Nodes (structure)

| Scene field | Source |
| --- | --- |
| `nodes[]` | AXP dump (`idb ui describe-all --json` or `iosef describe --json`), pruned like macOS |
| `id` | `n{i}` until the next `nodes` payload |
| `role` | map `AXRole` / type (`AXButton` → `button`, `AXTextField` → `textfield`, …) |
| `actions` | `press` on tappable roles; text fields accept `set` |
| `bounds` | AX frame in **points**, origin top-left of the screen |

If no AXP client is installed, `permissions.accessibility` is false and `nodes` is empty. Geometry ops still work via HID (`idb ui tap`, `iosef tap`, or Indigo).

## Act

| op | Implementation |
| --- | --- |
| `invoke` | tap node frame center (AXP / HID) |
| `set` | tap field, then type / paste |
| `hit` | HID tap at window-local points (`left` tap, `double`, `right` long-press) |
| `drag` / `scroll` | HID swipe |
| `key` | HID key; `cmd` is `unsupported` |
| `raise` | `simctl launch` / `simctl terminate` + launch for `params.app` bundle substring |

## Permissions

`permissions.accessibility`: AXP client responded.  
`permissions.screen_recording`: `simctl io screenshot` works (still do not stream full-screen JPEGs).

Socket: `$SCENEUSE_SOCK` or `/tmp/sceneuse-ios.sock`.

Device: `$SCENEUSE_IOS_UDID` or the unique booted simulator (`booted`).
