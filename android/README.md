# Android sandbox daemon

Host `sceneused` that speaks Scene / Act over a Unix socket. Tree from `uiautomator dump`; input from `adb shell input`. Fixture XML mode needs no emulator.

```sh
# always (in-memory dump, GTK-fixture analog)
make android-test
make android-smoke

# live device / emulator
adb devices
SCENEUSE_SOCK=/tmp/sceneuse-android.sock PYTHONPATH=android python3 -m sceneused
# other terminal:
SCENEUSE_SOCK=/tmp/sceneuse-android.sock PYTHONPATH=python python3 -m sceneuse scene --no-tiles
```

Default socket `/tmp/sceneuse-android.sock` so it does not steal macOS `/tmp/sceneuse.sock`. Point MCP at that sock to drive a phone instead of the Mac display.

`permissions.screen_recording` is false until sparse `screencap` tiles land. See [adapters/android.md](../adapters/android.md).
