"""adb wrapper. Serial from $SCENEUSE_ANDROID_SERIAL or the only connected device."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class AdbError(RuntimeError):
    pass


def default_adb() -> str:
    env = os.environ.get("SCENEUSE_ADB") or os.environ.get("ADB")
    if env:
        return env
    found = shutil.which("adb")
    if found:
        return found
    home = Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb"
    if home.exists():
        return str(home)
    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if android_home:
        cand = Path(android_home) / "platform-tools" / "adb"
        if cand.exists():
            return str(cand)
    return "adb"


class Adb:
    def __init__(self, binary: str | None = None, serial: str | None = None, timeout: float = 12.0):
        self.binary = binary or default_adb()
        self.serial = serial or os.environ.get("SCENEUSE_ANDROID_SERIAL") or None
        self.timeout = timeout

    def _argv(self, *args: str) -> list[str]:
        cmd = [self.binary]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        return cmd

    def run(self, *args: str, check: bool = True) -> str:
        try:
            proc = subprocess.run(
                self._argv(*args),
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as e:
            raise AdbError(f"adb not found ({self.binary})") from e
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"adb timed out: {' '.join(args)}") from e
        out = (proc.stdout or b"").decode("utf-8", "replace")
        err = (proc.stderr or b"").decode("utf-8", "replace")
        if check and proc.returncode != 0:
            raise AdbError((err or out or f"exit {proc.returncode}").strip())
        return out

    def devices(self) -> list[str]:
        text = self.run("devices", check=True)
        serials: list[str] = []
        for line in text.splitlines()[1:]:
            line = line.strip()
            if not line or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        return serials

    def connected(self) -> bool:
        try:
            return bool(self.devices())
        except AdbError:
            return False
