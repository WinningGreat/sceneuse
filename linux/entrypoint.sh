#!/usr/bin/env bash
# Boot Xvfb + session D-Bus + AT-SPI, then run daemon / smoke / shell.
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime}"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
export SCENEUSE_SOCK="${SCENEUSE_SOCK:-$XDG_RUNTIME_DIR/sceneuse.sock}"
export PYTHONPATH="/app/linux:/app/python${PYTHONPATH:+:$PYTHONPATH}"
export GTK_MODULES="${GTK_MODULES:-gail:atk-bridge}"
export GNOME_ACCESSIBILITY=1
export QT_ACCESSIBILITY=1
export NO_AT_BRIDGE=0

rm -f /tmp/.X99-lock "$SCENEUSE_SOCK" 2>/dev/null || true

Xvfb "$DISPLAY" -screen 0 1280x720x24 -ac +extension RANDR -noreset >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
sleep 0.4

if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
  # shellcheck disable=SC2046
  eval $(dbus-launch --sh-syntax)
fi

# AT-SPI session bus + registry (paths differ slightly by distro).
for launcher in /usr/libexec/at-spi-bus-launcher /usr/lib/at-spi2-core/at-spi-bus-launcher; do
  if [[ -x "$launcher" ]]; then
    "$launcher" --launch-immediately >/tmp/atspi-bus.log 2>&1 &
    break
  fi
done
sleep 0.3
for registry in /usr/libexec/at-spi2-registryd /usr/lib/at-spi2-core/at-spi2-registryd; do
  if [[ -x "$registry" ]]; then
    "$registry" >/tmp/atspi-registry.log 2>&1 &
    break
  fi
done
sleep 0.3

python3 /app/linux/fixtures/gtk_fixture.py >/tmp/fixture.log 2>&1 &
FIXTURE_PID=$!
sleep 0.8

cleanup() {
  kill "$FIXTURE_PID" 2>/dev/null || true
  kill "$XVFB_PID" 2>/dev/null || true
}
trap cleanup EXIT

cmd="${1:-daemon}"
shift || true

case "$cmd" in
  daemon)
    exec python3 -m sceneused "$@"
    ;;
  smoke)
    export SCENEUSE_SETTLE=0
    python3 -m sceneused >/tmp/sceneused.log 2>&1 &
    DAEMON_PID=$!
    sleep 0.6
    set +e
    SCENEUSE_SETTLE=0 python3 -m sceneuse smoke
    code=$?
    SCENEUSE_SETTLE=0 python3 /app/linux/smoke_loop.py
    loop=$?
    kill "$DAEMON_PID" 2>/dev/null || true
    wait "$DAEMON_PID" 2>/dev/null || true
    if [[ $code -ne 0 || $loop -ne 0 ]]; then
      echo "--- sceneused.log ---" >&2
      cat /tmp/sceneused.log >&2 || true
      echo "--- fixture.log ---" >&2
      cat /tmp/fixture.log >&2 || true
      exit 1
    fi
    exit 0
    ;;
  shell)
    exec bash "$@"
    ;;
  *)
    exec "$cmd" "$@"
    ;;
esac
