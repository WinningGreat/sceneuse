#!/bin/sh
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/macos/.build/release/sceneused"
APP="$ROOT/macos/.build/Sceneused.app"
if [ ! -x "$BIN" ]; then
  echo "build the daemon first: (cd macos && swift build -c release)" >&2
  exit 1
fi
mkdir -p "$APP/Contents/MacOS"
cp "$BIN" "$APP/Contents/MacOS/sceneused"
cp "$ROOT/macos/Info.plist" "$APP/Contents/Info.plist"
# Ad-hoc sign so TCC keys off this bundle, not the parent shell / Cursor.
codesign --force --deep --sign - "$APP" >/dev/null
echo "built $APP"
echo "run: open $APP"
echo "then grant Screen Recording + Accessibility to sceneused in System Settings"
