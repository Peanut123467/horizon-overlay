"""Local-only metrics for the stats HUD.

Everything here reads *our own* process and the machine's memory counters.
Nothing touches the game process -- no handle is opened on it, no injection, no
graphics API hooking. That is a deliberate boundary, which is also why there is
no game-FPS number here: reading presented-frame counts without injecting
requires an ETW consumer (the PresentMon approach), which is out of scope for
now. See the roadmap in the README.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from .win32 import MONITORINFO, gdi32, kernel32, user32

__all__ = ["Metrics", "snapshot", "process_memory_mb", "system_memory_percent", "refresh_rate_hz"]

_VREFRESH = 116
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class MONITORINFOEXW(MONITORINFO):
    _fields_ = [("szDevice", wintypes.WCHAR * 32)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


kernel32.K32GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
    wintypes.DWORD,
]
kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL

kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = wintypes.HANDLE

kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL

gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.GetDeviceCaps.restype = ctypes.c_int

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
gdi32.CreateDCW.restype = wintypes.HDC


@dataclass(frozen=True)
class Metrics:
    refresh_hz: int
    process_mb: float
    system_percent: int
    draw_ms: float

    def render(self) -> str:
        parts = []
        if self.refresh_hz > 0:
            parts.append(f"{self.refresh_hz}Hz")
        parts.append(f"内存 {self.process_mb:.0f}MB")
        parts.append(f"系统 {self.system_percent}%")
        if self.draw_ms > 0:
            parts.append(f"重绘 {self.draw_ms:.0f}ms")
        return "  ·  ".join(parts)


def process_memory_mb() -> float:
    """Working set of this process, in MiB."""
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    if not kernel32.K32GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        return 0.0
    return counters.WorkingSetSize / (1024 * 1024)


def system_memory_percent() -> int:
    """Physical memory load, 0-100."""
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0
    return int(status.dwMemoryLoad)


def refresh_rate_hz(hwnd=None) -> int:
    """Refresh rate of the window's monitor (primary when no window is given).

    ``GetDeviceCaps(VREFRESH)`` can report 0 or 1 for "hardware default", in
    which case we return 0 and the HUD omits the field rather than guessing.
    """
    if hwnd is not None:
        monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        if not monitor:
            return 0
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return 0
        hdc = gdi32.CreateDCW("DISPLAY", info.szDevice, None, None)
    else:
        hdc = user32.GetDC(None)
    if not hdc:
        return 0
    try:
        hz = int(gdi32.GetDeviceCaps(hdc, _VREFRESH))
    finally:
        if hwnd is not None:
            gdi32.DeleteDC(hdc)
        else:
            user32.ReleaseDC(None, hdc)
    return hz if hz > 1 else 0


def snapshot(draw_ms: float = 0.0, *, hwnd=None) -> Metrics:
    return Metrics(
        refresh_hz=refresh_rate_hz(hwnd),
        process_mb=process_memory_mb(),
        system_percent=system_memory_percent(),
        draw_ms=draw_ms,
    )
