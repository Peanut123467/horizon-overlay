"""Bridge between the control panel process and the running overlay.

The console runs as a separate process (``Horizon.exe --console``) because
pywebview needs the main thread, and the overlay owns a Win32 message loop.
They talk over ``WM_COPYDATA``: no TCP port, no temp files, no race between two
writers of ``config.json``. The overlay stays the only writer.
"""

from __future__ import annotations

import ctypes
import json
import re
from ctypes import wintypes
from multiprocessing.shared_memory import SharedMemory
from typing import Any
from uuid import uuid4

from .win32 import WM_COPYDATA, user32

__all__ = ["WM_COPYDATA", "OVERLAY_TITLE", "find_overlay", "send_payload", "read_payload"]

OVERLAY_TITLE = "Horizon Overlay"

# Tag values in COPYDATASTRUCT.dwData, so a stray sender cannot be mistaken for
# a legitimate one.
TAG_PATCH = 0x484F5249  # 'HORI'
_STATE_CAPACITY = 65536
_STATE_NAME = re.compile(r"HorizonState_[0-9a-f]{32}\Z")


class COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [
        ("dwData", ctypes.c_size_t),  # ULONG_PTR
        ("cbData", wintypes.DWORD),
        ("lpData", ctypes.c_void_p),
    ]


user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM


def find_overlay() -> int:
    """Return the overlay window handle, or 0 if it is not running."""
    return int(user32.FindWindowW(None, OVERLAY_TITLE) or 0)


def send_payload(hwnd: int, payload: dict[str, Any], tag: int = TAG_PATCH) -> bool:
    """Send ``payload`` as JSON. Returns True if the receiver acknowledged."""
    if not hwnd:
        return False
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    buffer = ctypes.create_string_buffer(data, len(data))
    struct = COPYDATASTRUCT(tag, len(data), ctypes.cast(buffer, ctypes.c_void_p))
    # LPARAM is an integer type, so the pointer has to be taken as c_void_p and
    # unwrapped -- ctypes.cast(..., LPARAM) is a TypeError.
    address = ctypes.cast(ctypes.byref(struct), ctypes.c_void_p).value
    result = ctypes.c_size_t()
    delivered = user32.SendMessageTimeoutW(
        wintypes.HWND(hwnd), WM_COPYDATA, 0, address or 0, 0x0002, 3000, ctypes.byref(result)
    )
    if delivered and result.value == 2:
        raise ValueError("快捷键已被其他程序占用，设置尚未保存，请更换键位")
    return bool(delivered and result.value == 1)


def read_payload(lparam: int) -> dict[str, Any] | None:
    """Parse an incoming WM_COPYDATA payload. Returns None if it is not ours."""
    try:
        struct = COPYDATASTRUCT.from_address(int(lparam))
    except (ValueError, TypeError):
        return None
    if struct.dwData != TAG_PATCH or not struct.cbData or not struct.lpData:
        return None
    raw = ctypes.string_at(struct.lpData, struct.cbData)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def query_state(hwnd: int) -> dict[str, Any] | None:
    """Read live settings using a short-lived, caller-owned memory mapping.

    WM_COPYDATA carries the request; the mapping carries the larger reply. No
    ports or disk files are used, including for nonpersistent CLI sessions.
    """
    if not hwnd:
        return None
    memory = SharedMemory(name="HorizonState_" + uuid4().hex, create=True, size=_STATE_CAPACITY)
    try:
        memory.buf[:4] = b"\0" * 4
        if not send_payload(hwnd, {"query": "state", "buffer": memory.name}):
            return None
        length = int.from_bytes(memory.buf[:4], "little")
        if not 0 < length <= _STATE_CAPACITY - 4:
            return None
        state = json.loads(bytes(memory.buf[4 : 4 + length]).decode("utf-8"))
        return state if isinstance(state, dict) and isinstance(state.get("config"), dict) else None
    except (ValueError, UnicodeError):
        return None
    finally:
        memory.close()
        memory.unlink()


def write_state(name: str, state: dict[str, Any]) -> bool:
    """Reply only into a correctly named mapping with sufficient capacity."""
    if not isinstance(name, str) or not _STATE_NAME.fullmatch(name):
        return False
    raw = json.dumps(state, ensure_ascii=False).encode("utf-8")
    if len(raw) + 4 > _STATE_CAPACITY:
        return False
    try:
        memory = SharedMemory(name=name)
    except OSError:
        return False
    try:
        if memory.size < len(raw) + 4:
            return False
        memory.buf[4 : 4 + len(raw)] = raw
        memory.buf[:4] = len(raw).to_bytes(4, "little")
        return True
    finally:
        memory.close()
