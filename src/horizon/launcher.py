"""Launch the local client and manage optional per-user startup."""

from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import sys
from contextlib import contextmanager
from ctypes import wintypes


def command(*args: str) -> list[str]:
    result = [sys.executable]
    if not getattr(sys, "frozen", False):
        result += ["-m", "horizon"]
    return result + list(args)


def launch(*args: str):
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        # The overlay must survive closing the onefile panel and its temp directory.
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    else:
        from pathlib import Path

        root = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.Popen(command(*args), env=env, creationflags=subprocess.CREATE_NO_WINDOW)


@contextmanager
def single_instance(name: str):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, "Local\\Horizon-" + name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    unique = ctypes.get_last_error() != 183
    try:
        yield unique
    finally:
        kernel.CloseHandle(handle)


def startup_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "Horizon")
            return value == subprocess.list2cmdline(command())
    except FileNotFoundError:
        return False


def set_startup(enabled: bool) -> None:
    import winreg

    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
    ) as key:
        if enabled:
            winreg.SetValueEx(key, "Horizon", 0, winreg.REG_SZ, subprocess.list2cmdline(command()))
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, "Horizon")
