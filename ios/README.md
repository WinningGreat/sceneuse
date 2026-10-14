# iOS Simulator sandbox daemon

Host `sceneused` that speaks Scene / Act over a Unix socket. Identity from `simctl`; nodes from AXP (`idb` / `iosef`) when installed. Fixture JSON mode needs no companion.

```sh
make ios-test
make ios-smoke

# live Simulator (booted device)
SCENEUSE_SOCK=/tmp/sceneuse-ios.sock PYTHONPATH=ios python3 -m sceneused
SCENEUSE_SOCK=/tmp/sceneuse-ios.sock PYTHONPATH=python python3 -m sceneuse status
```

Without `idb` or `iosef`, `status` reports `accessibility: false` and `nodes` stay empty — Mac AX of Simulator.app is chrome, not the iOS tree. Install an AXP client for invoke/set/hit.

Default socket `/tmp/sceneuse-ios.sock`. See [adapters/ios.md](../adapters/ios.md).
