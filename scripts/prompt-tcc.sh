#!/usr/bin/env bash
# Force TCC permission prompts for sceneused (run after tccutil reset if needed).
set -euo pipefail
APP="${1:-$HOME/Applications/Sceneused.app}"
SOCK="${SCENEUSE_SOCK:-/tmp/sceneuse.sock}"

if [ ! -d "$APP" ]; then
  echo "Missing $APP — run: make install-macos" >&2
  exit 1
fi

echo "==> Reset TCC for dev.sceneuse.sceneused (so prompts can appear again)"
tccutil reset ScreenCapture dev.sceneuse.sceneused 2>/dev/null || true
tccutil reset Accessibility dev.sceneuse.sceneused 2>/dev/null || true

echo "==> Stop duplicate daemons"
pkill -f 'Sceneused.app/Contents/MacOS/sceneused' 2>/dev/null || true
sleep 0.5
rm -f "$SOCK"

echo "==> Open System Settings → Privacy"
open "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ScreenCapture"
sleep 0.5
open "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Accessibility"

echo "==> Launch $APP (Allow on any sheet; sceneused should appear in Dock)"
SCENEUSE_SOCK="$SOCK" open "$APP"

echo ""
echo "If NO sheet appears, enable manually in the Privacy panes that just opened:"
echo "  • Screen Recording → sceneused ON"
echo "  • Accessibility → sceneused ON"
echo ""
echo "Then: PYTHONPATH=python python3 -m sceneuse doctor"
