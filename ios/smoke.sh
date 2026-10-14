#!/usr/bin/env bash
# Fixture-mode iOS daemon smoke (no idb/iosef required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOCK="/tmp/sceneuse-ios-smoke.sock"
export SCENEUSE_SOCK="$SOCK"
export SCENEUSE_IOS_FIXTURE="$ROOT/ios/fixtures/fixture.json"
export PYTHONPATH="$ROOT/ios"
rm -f "$SOCK"
python3 -m sceneused "$SOCK" >/tmp/sceneuse-ios-smoke.log 2>&1 &
DAEMON_PID=$!
cleanup() {
  kill "$DAEMON_PID" 2>/dev/null || true
  wait "$DAEMON_PID" 2>/dev/null || true
  rm -f "$SOCK"
}
trap cleanup EXIT
sleep 0.4
set +e
PYTHONPATH="$ROOT/python${PYTHONPATH:+:$PYTHONPATH}" python3 -m sceneuse smoke
code=$?
PYTHONPATH="$ROOT/python${PYTHONPATH:+:$PYTHONPATH}" python3 "$ROOT/ios/smoke_loop.py"
loop=$?
set -e
if [[ $code -ne 0 || $loop -ne 0 ]]; then
  echo "--- sceneused log ---" >&2
  cat /tmp/sceneuse-ios-smoke.log >&2 || true
  exit 1
fi
echo "ios smoke ok"
