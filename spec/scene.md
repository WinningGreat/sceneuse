# sceneuse protocol

Version **1**. Local NDJSON over a Unix socket. One observation (`scene`), one command family (`act`).

Pixels are a sparse fallback. The default payload is compositor metadata plus a pruned UI tree.

## Transport

- Default socket: `$SCENEUSE_SOCK` or `/tmp/sceneuse.sock`
- Framing: one UTF-8 JSON object per line (`\n`)
- Byte order / endianness: JSON numbers, no binary frames in v1
- Later: CBOR on the same envelope (`v` stays `1` until breaking changes)

The daemon accepts multiple clients. Capture starts on the first `subscribe` and stops when the last subscriber disconnects.

## Envelope

Every message:

| field | type | required | meaning |
| --- | --- | --- | --- |
| `v` | int | yes | protocol version, currently `1` |
| `type` | string | yes | message kind |
| `id` | string | requests | echoed on `ok` / `error` |
| `params` | object | some requests | see below |

Server may send unsolicited `scene` and `error` messages (`id` omitted on `scene`).

### Client → daemon

**hello** — handshake.

```json
{"v":1,"id":"1","type":"hello"}
```

**status** — permissions and adapter identity. Does not start capture.

```json
{"v":1,"id":"2","type":"status"}
```

**subscribe** — start (or keep) the scene stream.

```json
{"v":1,"id":"3","type":"subscribe","params":{"tiles":true}}
```

`params.tiles` (bool, default `true`): when `false`, never encode pixel tiles. Damage rects still stream.

**unsubscribe** — this connection stops receiving scenes. Capture continues if other subscribers exist.

**target** — set the observation handle (`params.window` and/or `params.app`). Empty params follows OS frontmost. Does not raise the window.

**act** — perform an action (see [Act](#act)).

### Daemon → client

**ok** — `result` is type-specific.

```json
{"v":1,"id":"1","type":"ok","result":{"protocol":1,"adapter":"macos","version":"0.1.0"}}
```

**error**

```json
{"v":1,"id":"4","type":"error","error":{"code":"permission_denied","message":"Accessibility is not granted"}}
```

Error codes: `bad_request`, `unknown_type`, `permission_denied`, `not_found`, `unsupported`, `internal`.

**scene** — observation. Fields live on the message itself (not nested) so a scene *is* the protocol observation.

## Scene

| field | type | full | delta | meaning |
| --- | --- | --- | --- | --- |
| `type` | `"scene"` | yes | yes | |
| `seq` | int | yes | yes | monotonic per daemon lifetime |
| `t` | number | yes | yes | seconds since Unix epoch |
| `kind` | `"full"` \| `"delta"` | yes | yes | |
| `permissions` | object | yes | yes | current TCC / trust state |
| `displays` | Display[] | yes | if changed | |
| `windows` | Window[] | yes | if changed | front-to-back |
| `cursor` | Cursor | yes | yes | |
| `focus` | Focus | yes | yes | |
| `damage` | Rect[] | yes | yes | dirty/move union since last emitted scene, logical points, top-left origin of the main display |
| `nodes` | Node[] | yes | if changed | pruned accessibility tree, focused window first |
| `tiles` | Tile[] | yes | yes | sparse JPEG patches; empty array if none |
| `node_count` | int | yes | if `nodes` present | nodes before prune, for debugging |

A **full** scene is sent:

- immediately after `subscribe`
- on focus change (different pid or window id)
- when the damage union covers more than ~40% of the focused display (layout-level change)

Otherwise **delta**: `damage` + `tiles` + `cursor` + `focus` + `permissions`. `windows` / `nodes` / `displays` omitted when unchanged. Clients merge onto the last full scene.

Coordinate space for `bounds`, `damage`, `cursor`, and node `bounds`: **logical points, origin top-left of the main display**. Window-local `hit` points are top-left of that window’s `bounds`.

### Display

```json
{"id":"d0","bounds":{"x":0,"y":0,"w":1470,"h":956},"scale":2,"color_space":"display_p3"}
```

### Window

```json
{
  "id": "w:1234",
  "pid": 412,
  "app": "Messages",
  "bundle": "com.apple.MobileSMS",
  "title": "Alice",
  "bounds": {"x":80,"y":40,"w":720,"h":640},
  "z": 0,
  "focused": true,
  "on_screen": true,
  "occluded": false
}
```

`z` is 0 for the frontmost listed window. `occluded` is true when a front-er window’s bounds fully contain this one.

### Cursor

```json
{"x":120,"y":80,"visible":true,"shape":"arrow"}
```

### Focus

```json
{"window":"w:1234","app":"Messages","pid":412}
```

OS frontmost window.

### Observe

```json
{"window":"w:1234","app":"Messages","pid":412}
```

Window whose AX tree is in `nodes`. Same as `focus` until the client sends `target`. Switch with:

```json
{"v":1,"id":"3","type":"target","params":{"window":"w:1234"}}
```

`params.app` is a substring (first on-screen match, unoccluded preferred). Empty params follows frontmost again. `subscribe` may pass the same `window` / `app` fields.

### Node

```json
{
  "id": "n14",
  "window": "w:1234",
  "role": "button",
  "name": "Send",
  "value": null,
  "states": ["enabled"],
  "actions": ["press"],
  "bounds": {"x":700,"y":640,"w":64,"h":28},
  "parent": "n3",
  "tags": ["target", "focus"]
}
```

Roles are normalized lowercase tokens (`button`, `textfield`, `textarea`, `checkbox`, `radio`, `slider`, `link`, `menuitem`, `tab`, `popup`, `heading`, `text`, `image`, `cell`, `row`, `list`, `outline`, `web`, `window`, `group`, `scrollarea`, `sheet`, `dialog`, `unknown`).

`id` is stable for the lifetime of one snapshot map (until the next `nodes` payload). `invoke` / `set` must use ids from the latest scene that included `nodes`.

`nodes` belong to **`observe`**, not necessarily the OS-frontmost window. `focus` is still whoever macOS considers frontmost (often the agent host). The agent picks a handle with `target` (`window` and/or `app`) and can switch. `raise` is a separate act when the OS needs that window in front (`key`, some apps). `invoke` / `set` work on the observed window without raising it.

`tags` are **salience hints**. The adapter still sends the full pruned tree. Models should weigh tagged nodes first:

| tag | meaning |
| --- | --- |
| `target` | best guess at the work surface (focused field, control under cursor, sheet button). At most one. |
| `focus` | AX-focused control, excluding noisy outline/cells |
| `cursor` | node bounds contain the pointer |
| `changed` | intersects recent compositor damage (small dirty rects only) |

Adapters prune: skip empty groups, cap depth, cap ~200 nodes, prefer interactive roles and named text. Do **not** drop the sidebar to fake a small scene; tag instead.

### Tile

```json
{
  "rect": {"x":100,"y":200,"w":80,"h":40},
  "mime": "image/jpeg",
  "data": "<base64>"
}
```

Rules:

- Never send a full-display JPEG as the primary observation.
- Encode a dirty rect only when it is **not** covered by a usable node (interactive or named).
- Skip a rect whose area is ≥ 40% of the display.
- Downscale any encoded tile so the long side is ≤ 512 px.
- If `tiles:false` on subscribe, `tiles` is always `[]`.

`data` is standard base64 (not URL-safe).

### Permissions

```json
{"screen_recording":true,"accessibility":true}
```

Missing screen recording: `windows` / `nodes` / `cursor` still stream when possible; `damage` and `tiles` are empty.

Missing accessibility: `nodes` empty; `invoke` / `set` return `permission_denied`. `hit` / `key` / `scroll` / `drag` may still work.

## Act

```json
{"v":1,"id":"4","type":"act","params":{...}}
```

Prefer semantic ops. Geometry is fallback.

After `act` the daemon waits about **1 second** (`SCENEUSE_SETTLE`, default `1`) so the UI can settle, emits a `scene`, then replies `ok`. Clients SHOULD treat that post-action scene (compact render) as the result — do not require a second `subscribe` / `scene` round-trip to see what changed. Fixture / CI can set `SCENEUSE_SETTLE=0`.

### invoke

```json
{"op":"invoke","node":"n14","action":"press"}
```

`action` is one of the node’s `actions` (`press`, `confirm`, `cancel`, `show_menu`, `pick`, `increment`, `decrement`). Default `press`.

### set

```json
{"op":"set","node":"n9","value":"hello"}
```

Focuses the node when possible, then sets its value (text fields).

### hit

```json
{"op":"hit","window":"w:1234","point":{"x":32,"y":14},"button":"left"}
```

`point` is **window-local** logical points. `button` is `left` (default), `right`, or `double`.

### key

```json
{"op":"key","keys":["cmd","c"]}
```

Tokens: `cmd`, `shift`, `alt`, `ctrl`, `fn`, letters, digits, `return`, `tab`, `escape`, `space`, `delete`, `backspace`, arrows (`up`,`down`,`left`,`right`), `f1`–`f12`. Goes to the OS-frontmost app. `raise` first if that is not the intended window.

### raise

```json
{"op":"raise","window":"w:1234"}
```

Activate the app and raise that window. Does not change `observe`. Use when `key` (or the app) requires frontmost.

### scroll

```json
{"op":"scroll","window":"w:1234","point":{"x":200,"y":200},"delta":{"x":0,"y":-240}}
```

`point` window-local; `delta` in points (positive `y` scrolls up / content moves down, matching typical pixel-delta wheel).

### drag

```json
{"op":"drag","window":"w:1234","from":{"x":10,"y":10},"to":{"x":10,"y":200}}
```

## Compact prompt render

Clients SHOULD expose a text rendering of the merged scene for LLMs. Example:

```
display 0 1470x956 @2x
focus: Cursor  pid=57821  win=w:1
observe: Messages  pid=412  win=w:1234
windows:
  [w:1234] Messages "Alice"  (observe)
  [w:1] Cursor "Cursor Agents"  (front)
damage: 2 rects
important:
  *[n9] textfield "iMessage" value="hello"  (target, focus)
  [n14] button "Send"  (changed)
nodes:
  *[n9] textfield "iMessage" value="hello"  (target, focus)
  [n3] window "Alice"
  [n14] button "Send"  (changed)
tiles: none
```

`important:` is the tagged subset, still followed by the full `nodes:` list. Star (`*`) marks `target`. Include `tiles: N` and skip dumping base64. Vision is only warranted when `tiles` is non-empty.

## JSON Schema

- [schema/envelope.schema.json](schema/envelope.schema.json)
- [schema/scene.schema.json](schema/scene.schema.json)
- [schema/act.schema.json](schema/act.schema.json)

## Adapter identity

`hello` `result.adapter` is `macos`, `windows`, `linux`, `android`, or `ios`. v1 ships `macos` plus sandbox daemons for `linux` / `android` / `ios`. See [adapters/windows.md](../adapters/windows.md), [adapters/linux.md](../adapters/linux.md), [adapters/android.md](../adapters/android.md), and [adapters/ios.md](../adapters/ios.md).

Mobile adapters use the same Scene / Act envelope. Differences:

- One logical display (the screen). `windows[]` is the foreground activity / scene, plus optional IME / status chrome.
- `cursor.visible` is `false` (touch). `hit` is a tap; `button` `double` is a double-tap; `right` is a long-press.
- `key` is IME / hardware keys (`back`, `home`, `return`, letters). No `cmd`.
- Compositor damage is usually unavailable. v1 streams `kind: full` on subscribe and after `act`; `tiles` stay empty unless a dirty-rect source exists. Do not send a full-screen JPEG as the observation.
