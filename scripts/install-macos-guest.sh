#!/usr/bin/env bash
# Build Sceneused.app and install it into a macOS guest (Lume / golden image).
# Run on the Mac host that has the sceneuse checkout + Swift toolchain, OR
# inside the guest if Xcode CLT can build there.
#
# Host → guest (typical golden bake):
#   ./scripts/install-macos-guest.sh --stage /tmp/Sceneused.app
#   lume ssh BUILDER -- mkdir -p /Users/lume/sceneuse-stage
#   # copy .app then:
#   lume ssh BUILDER -- bash -s < scripts/install-macos-guest.sh --from-staged /Users/lume/sceneuse-stage/Sceneused.app
#
# Inside guest after copy:
#   ./scripts/install-macos-guest.sh --from-staged ~/Sceneused.app
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOCK="${SCENEUSE_SOCK:-/tmp/sceneuse.sock}"
APP_DEST="${SCENEUSE_APP_DEST:-/Applications/Sceneused.app}"
LAUNCH_AGENT="${HOME}/Library/LaunchAgents/dev.sceneuse.sceneused.plist"
STAGE=""
FROM_STAGED=""
BUILD_ONLY=0

die() { echo "ERROR: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --stage) STAGE="$2"; shift 2 ;;
    --from-staged) FROM_STAGED="$2"; shift 2 ;;
    --build-only) BUILD_ONLY=1; shift ;;
    --dest) APP_DEST="$2"; shift 2 ;;
    *) die "unknown arg: $1" ;;
  esac
done

build_app() {
  echo "==> Building sceneused (release)"
  (cd "$ROOT/macos" && swift build -c release)
  echo "==> Bundling Sceneused.app"
  "$ROOT/scripts/bundle-macos.sh"
  local app="$ROOT/macos/.build/Sceneused.app"
  [ -d "$app" ] || die "bundle missing at $app"
  echo "$app"
}

install_launch_agent() {
  local app="$1"
  local bin="$app/Contents/MacOS/sceneused"
  [ -x "$bin" ] || die "no binary in $app"
  mkdir -p "$(dirname "$LAUNCH_AGENT")"
  cat >"$LAUNCH_AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>dev.sceneuse.sceneused</string>
  <key>ProgramArguments</key>
  <array>
    <string>$bin</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SCENEUSE_SOCK</key>
    <string>$SOCK</string>
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
  launchctl bootout "gui/$(id -u)/dev.sceneuse.sceneused" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENT" 2>/dev/null \
    || launchctl load -w "$LAUNCH_AGENT" 2>/dev/null \
    || true
  echo "    LaunchAgent: $LAUNCH_AGENT"
}

if [ -n "$FROM_STAGED" ]; then
  [ -d "$FROM_STAGED" ] || die "staged app not found: $FROM_STAGED"
  echo "==> Installing $FROM_STAGED → $APP_DEST"
  rm -rf "$APP_DEST"
  cp -R "$FROM_STAGED" "$APP_DEST"
  install_launch_agent "$APP_DEST"
  open "$APP_DEST" 2>/dev/null || true
  echo "OK Sceneused.app installed"
  echo "    Grant Screen Recording + Accessibility to sceneused in System Settings"
  echo "    Socket: $SOCK"
  exit 0
fi

APP="$(build_app)"
if [ -n "$STAGE" ]; then
  rm -rf "$STAGE"
  cp -R "$APP" "$STAGE"
  echo "OK staged at $STAGE"
  exit 0
fi

if [ "$BUILD_ONLY" = 1 ]; then
  echo "OK built $APP"
  exit 0
fi

echo "==> Installing $APP → $APP_DEST"
rm -rf "$APP_DEST"
cp -R "$APP" "$APP_DEST"
install_launch_agent "$APP_DEST"
open "$APP_DEST" 2>/dev/null || true
echo "OK Sceneused.app installed at $APP_DEST"
echo "    Grant Screen Recording + Accessibility to sceneused"
