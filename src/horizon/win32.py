"""Minimal Win32 bindings for a click-through, always-on-top layered window.

Only what Horizon needs:

* per-monitor DPI awareness
* monitor enumeration (physical pixels)
* a per-pixel-alpha layered window via ``UpdateLayeredWindow``
* global hotkeys and a classic message loop

No third-party dependency -- pure ``ctypes``.  Windows only by design.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

__all__ = [
    "list_monitors",
    "set_dpi_aware",
    "create_overlay_window",
    "LayeredSurface",
    "present",
    "show",
    "hide",
    "resize",
    "reassert_topmost",
    "run_message_loop",
    "post_quit",
    "post_app_message",
    "register_hotkey",
    "set_timer",
    "kill_timer",
    "destroy_window",
    "user32",
    "HWND_TOPMOST",
    "SWP_NOACTIVATE",
    "MOD_ALT",
    "MOD_CONTROL",
    "MOD_SHIFT",
    "MOD_NOREPEAT",
    "WM_HOTKEY",
    "WM_TIMER",
    "WM_DISPLAYCHANGE",
    "WM_COPYDATA",
    "WM_CLOSE",
    "WM_DESTROY",
    "WM_APP",
]

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------- constants --

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

BI_RGB = 0
DIB_RGB_COLORS = 0

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COPYDATA = 0x004A
WM_TIMER = 0x0113
WM_DISPLAYCHANGE = 0x007E
WM_HOTKEY = 0x0312
WM_APP = 0x8000

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

# DPI awareness contexts
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


# ----------------------------------------------------------------- structs ---


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


# ---------------------------------------------------------------- bindings ---

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT

user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL

user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE),
    wintypes.HDC,
    ctypes.POINTER(POINT),
    wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC

user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL

user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
user32.SetTimer.restype = ctypes.c_size_t

user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wintypes.BOOL

user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL

user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]

user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    ctypes.c_void_p,
    wintypes.LPARAM,
]
user32.EnumDisplayMonitors.restype = wintypes.BOOL

user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC

gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP

gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ

gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    wintypes.LPARAM,
)


# ---------------------------------------------------------------- helpers ----


def set_dpi_aware() -> None:
    """Opt into per-monitor DPI awareness so coordinates are physical pixels."""
    try:
        ctx = _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(ctx.value)):
            return
    except (AttributeError, OSError):
        pass
    try:
        # Fallback for Windows 8.1: PROCESS_PER_MONITOR_DPI_AWARE == 2
        shcore = ctypes.WinDLL("shcore")
        shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def list_monitors() -> list[tuple[int, int, int, int]]:
    """Return ``[(x, y, width, height), ...]`` in physical pixels, primary first."""
    found: list[tuple[bool, tuple[int, int, int, int]]] = []

    def _cb(hmon, _hdc, _rect, _lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            found.append(
                (bool(info.dwFlags & 1), (r.left, r.top, r.right - r.left, r.bottom - r.top))
            )
        return True

    user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(_cb), 0)
    if not found:  # pragma: no cover - defensive
        return [(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))]
    found.sort(key=lambda item: (not item[0], item[1][0], item[1][1]))
    return [rect for _primary, rect in found]


class LayeredSurface:
    """A 32-bit top-down DIB section used as the window's backing store.

    ``blit`` accepts tightly packed **BGRA premultiplied** bytes, which is what
    ``UpdateLayeredWindow`` expects with ``AC_SRC_ALPHA``.
    """

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._screen_dc = user32.GetDC(None)
        self._mem_dc = gdi32.CreateCompatibleDC(self._screen_dc)

        bmi = BITMAPINFO()
        hdr = bmi.bmiHeader
        hdr.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        hdr.biWidth = width
        hdr.biHeight = -height  # negative == top-down
        hdr.biPlanes = 1
        hdr.biBitCount = 32
        hdr.biCompression = BI_RGB

        self._bits = ctypes.c_void_p()
        self._hbmp = gdi32.CreateDIBSection(
            self._mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(self._bits), None, 0
        )
        if not self._hbmp:
            raise OSError(ctypes.get_last_error(), "CreateDIBSection failed")
        self._old = gdi32.SelectObject(self._mem_dc, self._hbmp)

    @property
    def nbytes(self) -> int:
        return self.width * self.height * 4

    def blit(self, data: bytes) -> None:
        if len(data) != self.nbytes:
            raise ValueError(f"expected {self.nbytes} bytes, got {len(data)}")
        ctypes.memmove(self._bits, data, self.nbytes)

    def release(self) -> None:
        if self._hbmp:
            gdi32.SelectObject(self._mem_dc, self._old)
            gdi32.DeleteObject(self._hbmp)
            self._hbmp = None
        if self._mem_dc:
            gdi32.DeleteDC(self._mem_dc)
            self._mem_dc = None
        if self._screen_dc:
            user32.ReleaseDC(None, self._screen_dc)
            self._screen_dc = None


def create_overlay_window(
    x: int, y: int, width: int, height: int, wndproc: WNDPROC, title: str = "Horizon Overlay"
) -> wintypes.HWND:
    """Create a borderless, click-through, non-activating topmost window."""
    hinst = kernel32.GetModuleHandleW(None)
    class_name = f"HorizonOverlay_{os.getpid()}"

    wc = WNDCLASSW()
    wc.style = 0
    wc.lpfnWndProc = wndproc
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = hinst
    wc.hIcon = None
    wc.hCursor = None
    wc.hbrBackground = None
    wc.lpszMenuName = None
    wc.lpszClassName = class_name

    if not user32.RegisterClassW(ctypes.byref(wc)):
        err = ctypes.get_last_error()
        if err not in (0, 1410):  # 1410 == class already exists
            raise OSError(err, "RegisterClassW failed")

    ex_style = (
        WS_EX_LAYERED
        | WS_EX_TRANSPARENT  # click-through
        | WS_EX_TOPMOST
        | WS_EX_TOOLWINDOW  # keep out of Alt-Tab
        | WS_EX_NOACTIVATE  # never steal focus from the game
    )

    hwnd = user32.CreateWindowExW(
        ex_style,
        class_name,
        title,
        WS_POPUP,
        x,
        y,
        width,
        height,
        None,
        None,
        hinst,
        None,
    )
    if not hwnd:
        raise OSError(ctypes.get_last_error(), "CreateWindowExW failed")
    return hwnd


def resize(hwnd: wintypes.HWND, x: int, y: int, width: int, height: int) -> None:
    """Move/resize while keeping the window topmost and unfocused."""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, width, height, SWP_NOACTIVATE)


def present(hwnd: wintypes.HWND, surface: LayeredSurface, x: int, y: int) -> None:
    """Push the DIB contents to the screen with per-pixel alpha."""
    pt_dst = POINT(x, y)
    size = SIZE(surface.width, surface.height)
    pt_src = POINT(0, 0)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    ok = user32.UpdateLayeredWindow(
        hwnd,
        surface._screen_dc,
        ctypes.byref(pt_dst),
        ctypes.byref(size),
        surface._mem_dc,
        ctypes.byref(pt_src),
        0,
        ctypes.byref(blend),
        ULW_ALPHA,
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "UpdateLayeredWindow failed")


def show(hwnd: wintypes.HWND) -> None:
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)


def hide(hwnd: wintypes.HWND) -> None:
    user32.ShowWindow(hwnd, SW_HIDE)


def reassert_topmost(hwnd: wintypes.HWND) -> None:
    """Some fullscreen-ish games re-order z; nudge ourselves back to the top."""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def register_hotkey(hwnd: wintypes.HWND, hotkey_id: int, mods: int, vk: int) -> bool:
    return bool(user32.RegisterHotKey(hwnd, hotkey_id, mods | MOD_NOREPEAT, vk))


def set_timer(hwnd: wintypes.HWND, timer_id: int, ms: int) -> None:
    user32.SetTimer(hwnd, timer_id, ms, None)


def kill_timer(hwnd: wintypes.HWND, timer_id: int) -> None:
    user32.KillTimer(hwnd, timer_id)


def post_app_message(hwnd: wintypes.HWND, code: int, wparam: int = 0, lparam: int = 0) -> None:
    user32.PostMessageW(hwnd, WM_APP + code, wparam, lparam)


def destroy_window(hwnd: wintypes.HWND) -> None:
    user32.DestroyWindow(hwnd)


def run_message_loop() -> None:
    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def post_quit() -> None:
    user32.PostQuitMessage(0)
