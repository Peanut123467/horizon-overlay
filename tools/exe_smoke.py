"""Verify the packaged client opens a panel without starting the overlay."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from horizon import ipc  # noqa: E402


def main():
    import clr

    framework = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET"
        / "Framework64"
        / "v4.0.30319"
        / "WPF"
    )
    clr.AddReference(str(framework / "UIAutomationClient.dll"))
    clr.AddReference(str(framework / "UIAutomationTypes.dll"))
    from System import IntPtr
    from System.Windows.Automation import (
        AutomationElement,
        InvokePattern,
        PropertyCondition,
        TreeScope,
    )

    user32 = ctypes.WinDLL("user32")
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    if ipc.find_overlay() or user32.FindWindowW(None, "Horizon 控制台"):
        raise SystemExit("Close Horizon before the packaged client check.")
    cfg_path = Path(tempfile.mkdtemp(dir=ROOT / ".runtime")) / "config.json"
    command = [str(ROOT / "dist" / "Horizon.exe"), "--config", str(cfg_path)]
    env = os.environ.copy()
    env["HORIZON_WEBVIEW_ARGS"] = "--in-process-gpu --force-renderer-accessibility"
    child = subprocess.Popen(command, env=env)
    children = [child]
    started = False
    hwnd = None

    def wait_overlay(alive):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if bool(ipc.find_overlay()) == alive:
                return
            time.sleep(0.2)
        raise AssertionError(f"overlay alive did not become {alive}")

    def click(name):
        root = AutomationElement.FromHandle(IntPtr(hwnd))
        element = root.FindFirst(
            TreeScope.Descendants, PropertyCondition(AutomationElement.NameProperty, name)
        )
        assert element is not None, f"button missing: {name}"
        element.GetCurrentPattern(InvokePattern.Pattern).Invoke()

    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            hwnd = user32.FindWindowW(None, "Horizon 控制台")
            if hwnd and user32.IsWindowVisible(hwnd):
                break
            if child.poll() is not None:
                raise RuntimeError(f"Packaged client exited early: {child.returncode}")
            time.sleep(0.25)
        assert hwnd and user32.IsWindowVisible(hwnd), "control panel did not appear"
        time.sleep(3)
        assert not ipc.find_overlay(), "default launch unexpectedly started overlay"
        print("PASS packaged client opens a visible panel only", flush=True)
        duplicate = subprocess.run([str(ROOT / "dist" / "Horizon.exe")], timeout=15)
        assert duplicate.returncode == 0
        print("PASS duplicate launch reuses existing panel", flush=True)
        click("启动叠加层")
        wait_overlay(True)
        started = True
        time.sleep(1)
        print("PASS packaged panel button launches overlay", flush=True)
        from horizon.config import default_config, load

        saved = load(cfg_path)
        saved.tray_hint_shown = False
        assert saved.to_dict() == default_config().to_dict()
        print("PASS packaged defaults match selected settings", flush=True)
        user32.PostMessageW(hwnd, 0x0010, 0, 0)
        child.wait(timeout=12)
        assert child.returncode == 0
        assert ipc.find_overlay()
        assert ipc.send_payload(ipc.find_overlay(), {"patch": {"frame": {"width": 13}}})
        print("PASS overlay survives panel closure and accepts changes", flush=True)
        child = subprocess.Popen(command, env=env)
        children.append(child)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            hwnd = user32.FindWindowW(None, "Horizon 控制台")
            if hwnd and user32.IsWindowVisible(hwnd):
                break
            time.sleep(0.2)
        assert hwnd
        time.sleep(3)
        click("停止叠加层")
        wait_overlay(False)
        started = False
        print("PASS reopened panel controls existing overlay", flush=True)
        user32.PostMessageW(hwnd, 0x0010, 0, 0)
        child.wait(timeout=12)
        assert child.returncode == 0
        print("PASS packaged client closes cleanly", flush=True)
    finally:
        if hwnd:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        if started and ipc.find_overlay():
            from horizon.overlay import APP_QUIT
            from horizon.win32 import post_app_message

            post_app_message(ipc.find_overlay(), APP_QUIT)
        for process in children:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
