#!/usr/bin/env bash
# Install sceneuse for local MCP use on this Mac (build, copy app, LaunchAgent).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${SCENEUSE_APP_DEST:-$HOME/Applications/Sceneused.app}"
SOCK="${SCENEUSE_SOCK:-/tmp/sceneuse.sock}"
LABEL="dev.sceneuse.sceneused"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

echo "==> Building Sceneused.app"
(cd "$ROOT/macos" && swift build -c release)
"$ROOT/scripts/bundle-macos.sh"

SRC="$ROOT/macos/.build/Sceneused.app"
[ -d "$SRC" ] || { echo "missing $SRC"; exit 1; }

echo "==> Installing to $DEST"
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -R "$SRC" "$DEST"

BIN="$DEST/Contents/MacOS/sceneused"
mkdir -p "$(dirname "$PLIST")"
cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${BIN}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SCENEUSE_SOCK</key>
    <string>${SOCK}</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/sceneused.out.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/sceneused.err.log</string>
</dict>
</plist>
EOF

echo "==> Stopping any old sceneused (avoid duplicate daemons)"
pkill -f 'Sceneused.app/Contents/MacOS/sceneused' 2>/dev/null || true
pkill -f '/macos/.build/release/sceneused' 2>/dev/null || true
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
sleep 0.5
rm -f "$SOCK"

launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"

echo "==> Starting daemon — look for sceneused in the Dock; Allow both TCC sheets"
open "$DEST"

sleep 2
PYTHONPATH="$ROOT/python" SCENEUSE_SOCK="$SOCK" python3 -m sceneuse doctor --open-settings || true

echo ""
echo "Done. MCP: PYTHONPATH=$ROOT/python python3 -m sceneuse mcp"
echo "Doctor: PYTHONPATH=$ROOT/python python3 -m sceneuse doctor"
