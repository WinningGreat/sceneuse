# Baking sceneuse into golden images

Ship the **daemon on the guest**, not Playwright-inside-sceneuse. Mac and Linux
get different binaries; same NDJSON protocol and `$SCENEUSE_SOCK`.

| Guest | Artifact | Install |
| --- | --- | --- |
| macOS (Lume / Cua) | `Sceneused.app` | `scripts/install-macos-guest.sh` |
| Linux desktop (E2B, Daytona, Cua Docker) | Python AT-SPI `sceneused` | `scripts/install-linux.sh` |
| Android emulator | Host Python `android/sceneused` + `adb` | `PYTHONPATH=android python3 -m sceneused` (sock `/tmp/sceneuse-android.sock`) |
| iOS Simulator | Host Python `ios/sceneused` + `simctl` | `PYTHONPATH=ios python3 -m sceneused` (sock `/tmp/sceneuse-ios.sock`); AXP via `idb`/`iosef` for nodes |

## Linux

```sh
# deps on the image
sudo apt-get install -y python3 python3-gi gir1.2-atspi-2.0 at-spi2-core dbus-x11

# from this repo (or a staged copy of linux/)
sudo ./scripts/install-linux.sh
# later, once DISPLAY / AT-SPI are up:
pairspace-sceneused-start
```

Pairspace vendors a copy under `virtual-office/backend/vendor/sceneuse-linux`
and bakes it into the `browser-desktop` template / Cua Linux golden Dockerfile.

## macOS

On an Apple Silicon host with Swift:

```sh
./scripts/install-macos-guest.sh --stage /tmp/Sceneused.app
# copy into the Lume builder, then inside the guest:
./scripts/install-macos-guest.sh --from-staged /Users/lume/Sceneused.app
```

Grant **Screen Recording** + **Accessibility** to **sceneused** once on the
builder, then clone that VM as the golden base (`build-macos-golden.sh`).

## Can you host these so others use them?

**Yes, with the usual image-distribution limits:**

| Provider | What you can share | How others get it |
| --- | --- | --- |
| **Cua Linux (Docker)** | Your tagged image (e.g. `ghcr.io/<org>/pairspace-cua-linux:sceneuse`) | They `docker pull` / set `CUA_LINUX_IMAGE` (or you publish public ECR/GHCR) |
| **Cua macOS (Lume)** | A golden VM name / exported Lume image on a machine you control | They pull your published Lume image **or** re-run `build-macos-golden.sh` (TCC often must be granted on their hardware) |
| **E2B** | Not one global template for every customer under BYOK | Each org builds the same Dockerfile in **their** E2B account (`ensureTemplate` / `build-e2b-template.ts`). You host the *recipe* (Dockerfile + vendor tree), not a shared running template |
| **Daytona / Morph** | Snapshot you create in that vendor | Share snapshot id inside your org, or publish the Dockerfile/scripts so they rebuild |

So: **host registries + build scripts for others**; don’t expect a single E2B template id to work across arbitrary BYOK keys. Mac golden sharing is strongest as “our Lume image + docs”, weakest as “one TCC-blessed VM that clones cleanly onto every Mac” (Apple permissions are sticky to the machine/image identity).

## Smoke

Linux (Docker sandbox in this repo): `make linux-smoke`  
macOS guest: `make status` / `make smoke` with `SCENEUSE_SOCK=/tmp/sceneuse.sock`
