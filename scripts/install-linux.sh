#!/usr/bin/env bash
# Install Linux sceneused into a desktop image (E2B / Daytona / Cua Linux / Docker).
# Run from a sceneuse checkout, or with SCENEUSE_LINUX_SRC pointing at a staged tree.
#
#   sudo ./scripts/install-linux.sh
#   PREFIX=/opt/sceneuse ./scripts/install-linux.sh
#
set -euo pipefail

PREFIX="${PREFIX:-/opt/sceneuse}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -n "${SCENEUSE_LINUX_SRC:-}" ]; then
  SRC="$SCENEUSE_LINUX_SRC"
elif [ -d "$SCRIPT_DIR/sceneused" ]; then
  # Staged / vendored layout: install-linux.sh sits next to sceneused/
  SRC="$SCRIPT_DIR"
elif [ -d "$ROOT/linux/sceneused" ]; then
  SRC="$ROOT/linux"
else
  SRC="$ROOT/linux"
fi

die() { echo "ERROR: $*" >&2; exit 1; }

[ -d "$SRC/sceneused" ] || die "missing $SRC/sceneused (set SCENEUSE_LINUX_SRC)"

echo "==> Installing sceneused (linux) → $PREFIX"
mkdir -p "$PREFIX"
rm -rf "$PREFIX/sceneused"
cp -a "$SRC/sceneused" "$PREFIX/sceneused"
# Optional fixtures for smoke inside the image
if [ -d "$SRC/fixtures" ]; then
  rm -rf "$PREFIX/fixtures"
  cp -a "$SRC/fixtures" "$PREFIX/fixtures"
fi

install -d "$(dirname "$PREFIX")/bin" 2>/dev/null || true
WRAPPER="${SCENEUSE_WRAPPER:-/usr/local/bin/sceneused}"
cat >"$WRAPPER" <<EOF
#!/bin/sh
export PYTHONPATH="$PREFIX\${PYTHONPATH:+:\$PYTHONPATH}"
export SCENEUSE_SOCK="\${SCENEUSE_SOCK:-\${XDG_RUNTIME_DIR:-/tmp}/sceneuse.sock}"
exec python3 -m sceneused "\$@"
EOF
chmod +x "$WRAPPER"

# Desktop autostart (ignored headless; harmless). Prefer Pairspace starting the
# daemon after DISPLAY is up on VNC images.
AUTOSTART_DIR="${XDG_CONFIG_HOME:-/etc/xdg}/autostart"
if mkdir -p "$AUTOSTART_DIR" 2>/dev/null; then
  cat >"$AUTOSTART_DIR/sceneused.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=sceneused
Comment=sceneuse compositor-scene daemon (AT-SPI)
Exec=$WRAPPER
X-GNOME-Autostart-enabled=true
EOF
fi

# Helper used by Pairspace / golden boots once Xvfb or a real session exists.
cat >"/usr/local/bin/pairspace-sceneused-start" <<EOF
#!/bin/sh
set -e
export SCENEUSE_SOCK="\${SCENEUSE_SOCK:-\${XDG_RUNTIME_DIR:-/tmp}/sceneuse.sock}"
mkdir -p "\$(dirname "\$SCENEUSE_SOCK")"
# Already running?
if [ -S "\$SCENEUSE_SOCK" ]; then
  python3 -c "import socket,os;s=socket.socket(socket.AF_UNIX);s.settimeout(1);s.connect(os.environ['SCENEUSE_SOCK']);s.close()" 2>/dev/null && exit 0
fi
# AT-SPI bus (best-effort)
for launcher in /usr/libexec/at-spi-bus-launcher /usr/lib/at-spi2-core/at-spi-bus-launcher; do
  [ -x "\$launcher" ] || continue
  "\$launcher" --launch-immediately >/tmp/atspi-bus.log 2>&1 &
  break
done
for registry in /usr/libexec/at-spi2-registryd /usr/lib/at-spi2-core/at-spi2-registryd; do
  [ -x "\$registry" ] || continue
  "\$registry" >/tmp/atspi-registry.log 2>&1 &
  break
done
export GTK_MODULES="\${GTK_MODULES:-gail:atk-bridge}"
export GNOME_ACCESSIBILITY=1
export NO_AT_BRIDGE=0
nohup $WRAPPER >/tmp/sceneused.log 2>&1 &
i=0
while [ \$i -lt 30 ]; do
  [ -S "\$SCENEUSE_SOCK" ] && exit 0
  i=\$((i+1)); sleep 0.2
done
echo "sceneused did not create \$SCENEUSE_SOCK — see /tmp/sceneused.log" >&2
exit 1
EOF
chmod +x /usr/local/bin/pairspace-sceneused-start

echo "OK sceneused linux"
echo "    binary:  $WRAPPER"
echo "    start:   pairspace-sceneused-start"
echo "    socket:  \$SCENEUSE_SOCK or \$XDG_RUNTIME_DIR/sceneuse.sock"
echo "    deps:    python3-gi gir1.2-atspi-2.0 at-spi2-core (apt)"
