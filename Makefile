.PHONY: daemon bundle inspector smoke status scene loop native doctor install-macos linux-image linux-smoke linux-shell android-test android-smoke ios-test ios-smoke

SOCK ?= /tmp/sceneuse.sock
export SCENEUSE_SOCK=$(SOCK)
APP := macos/.build/Sceneused.app
LINUX_IMAGE ?= sceneuse-linux

daemon: bundle ## build Sceneused.app and run it (TCC identity = sceneused)
	@pkill -f 'Sceneused.app/Contents/MacOS/sceneused' 2>/dev/null || true
	@pkill -f '/macos/.build/release/sceneused' 2>/dev/null || true
	@sleep 0.3
	SCENEUSE_SOCK=$(SOCK) open "$(APP)"
	@echo "sceneused via $(APP) on $(SOCK)"
	@echo "grant Screen Recording + Accessibility to sceneused if status shows false"

bundle: ## wrap the binary in an .app so TCC Screen Recording attaches to sceneused
	cd macos && swift build -c release
	./scripts/bundle-macos.sh

inspector:
	PYTHONPATH=python python3 -m sceneuse inspector

smoke:
	PYTHONPATH=python python3 -m sceneuse smoke

doctor: ## permissions, socket, MCP snippet; use --fix to restart daemon
	PYTHONPATH=python python3 -m sceneuse doctor

install-macos: bundle ## ~/Applications + LaunchAgent + doctor
	./scripts/install-macos-local.sh

status:
	PYTHONPATH=python python3 -m sceneuse status

scene:
	PYTHONPATH=python python3 -m sceneuse scene --no-tiles

loop:
	PYTHONPATH=python python3 python/examples/loop.py

native:
	PYTHONPATH=python python3 python/examples/native.py

linux-image: ## build Ubuntu+AT-SPI sandbox image
	docker build -t $(LINUX_IMAGE) -f linux/Dockerfile .

linux-smoke: linux-image ## Xvfb + AT-SPI fixture + hello/status/set/invoke
	docker run --rm --platform linux/arm64 \
		-v "$(CURDIR):/app" -w /app $(LINUX_IMAGE) smoke

linux-shell: linux-image ## interactive shell in the Linux sandbox
	docker run --rm -it --platform linux/arm64 \
		-v "$(CURDIR):/app" -w /app $(LINUX_IMAGE) shell

android-test: ## uiautomator dump → nodes (no emulator)
	PYTHONPATH=android python3 -m unittest discover -s android/tests -q

android-smoke: android-test ## fixture daemon hello/status/set/invoke
	chmod +x android/smoke.sh
	./android/smoke.sh

ios-test: ## fixture AXP tree → nodes (no idb)
	PYTHONPATH=ios python3 -m unittest discover -s ios/tests -q

ios-smoke: ios-test ## fixture daemon hello/status/set/invoke
	chmod +x ios/smoke.sh
	./ios/smoke.sh
