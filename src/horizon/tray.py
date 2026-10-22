"""Tray icon -- the app's home while it runs.

The icon lives in the notification area (bottom-right on Windows). Left click
toggles the overlay, right click opens the menu, and 退出 shuts everything down.

The tray runs pystray in a daemon thread and talks to the overlay window via
``PostMessage`` -- it never touches overlay state directly.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Callable
from pathlib import Path

from . import __version__, win32
from .config import COLOR_PALETTE
from .overlay import (
    APP_QUIT,
    APP_RELOAD,
    APP_SET,
    APP_TOGGLE,
    PRESET_LABELS,
    PRESET_NAMES,
    SET_COLOR,
    SET_FRAME,
    SET_GRID,
    SET_PRESET,
    SET_RETICLE,
    SET_STATS,
    SET_VIGNETTE,
    VIGNETTE_LABELS,
    VIGNETTE_LEVELS,
)

__all__ = ["start_tray", "refresh_icon", "make_icon_image"]

COLOR_NAMES: dict[str, str] = {
    "#00FF66": "亮绿",
    "#00E5FF": "青",
    "#FFFFFF": "白",
    "#FFD60A": "暖黄",
    "#B388FF": "淡紫",
}

# Only the sections a preset actually controls. Colour and HUD settings are
# user preferences, so they must not stop a preset from matching.
_PRESET_SECTIONS = ("vignette", "frame", "reticle", "grid")


def _preset_key(app) -> str | None:
    """Which named preset the current config matches, or None if hand-tuned."""
    from .config import preset

    current = app.cfg.to_dict()
    for name in PRESET_NAMES:
        target = preset(name).to_dict()
        if all(current[section] == target[section] for section in _PRESET_SECTIONS):
            return name
    return None


def _vignette_level(app) -> float:
    v = app.cfg.vignette
    return float(v.strength) if v.enabled else 0.0


def make_icon_image(color: str = "#00FF66"):
    """Draw the tray icon as RGBA, tinted with the current accent colour."""
    from PIL import Image, ImageDraw

    from .render import parse_color

    r, g, b = parse_color(color)
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((7, 7, size - 7, size - 7), radius=10, outline=(r, g, b, 255), width=5)
    d.ellipse((28, 28, 36, 36), fill=(r, g, b, 255))
    d.line((32, 2, 32, 10), fill=(r, g, b, 255), width=4)
    d.line((32, size - 10, 32, size - 2), fill=(r, g, b, 255), width=4)
    d.line((2, 32, 10, 32), fill=(r, g, b, 255), width=4)
    d.line((size - 10, 32, size - 2, 32), fill=(r, g, b, 255), width=4)
    return img


def refresh_icon(icon, color: str) -> None:
    """Repaint the tray icon after the accent colour changes."""
    if icon is None:
        return
    with contextlib.suppress(Exception):  # cosmetic only
        icon.icon = make_icon_image(color)


def start_tray(app, log: Callable[[str], None] = print):
    """Start the tray icon in a background thread. Returns the Icon or None."""
    try:
        import pystray
    except ImportError:
        log("[horizon] pystray is missing -- no tray icon. Run: pip install pystray")
        return None

    def _post(code: int) -> bool:
        hwnd = app.hwnd
        if hwnd:
            win32.post_app_message(hwnd, code)
            return True
        return False

    def on_toggle(_icon, _item):
        _post(APP_TOGGLE)

    def on_console(_icon, _item):
        from .launcher import launch

        launch("--console", "--config", str(app.cfg_path))

    def on_reload(_icon, _item):
        _post(APP_RELOAD)

    def on_open_config(_icon, _item):
        p = Path(app.cfg_path) if app.cfg_path else None
        if p and p.parent.exists():
            try:
                os.startfile(str(p.parent))  # noqa: S606 - Windows shell open
            except OSError as exc:
                log(f"[horizon] could not open config folder: {exc!r}")

    def on_quit(_icon, _item):
        posted = _post(APP_QUIT)
        _icon.stop()
        if not posted:
            # No window left to receive the message: nothing to wind down.
            os._exit(0)

    def _setter(action: int, value: int):
        def _handler(_icon, _item):
            hwnd = app.hwnd
            if hwnd:
                win32.post_app_message(hwnd, APP_SET, action, value)

        return _handler

    def _is_color(hex_value: str):
        return lambda _item: app.cfg.color.strip().upper() == hex_value.upper()

    color_menu = pystray.Menu(
        *[
            pystray.MenuItem(
                f"{COLOR_NAMES.get(hex_value.upper(), '自定义')}  {hex_value}",
                _setter(SET_COLOR, index),
                checked=_is_color(hex_value),
                radio=True,
            )
            for index, hex_value in enumerate(COLOR_PALETTE)
        ]
    )

    preset_menu = pystray.Menu(
        *[
            pystray.MenuItem(
                label,
                _setter(SET_PRESET, index),
                checked=(lambda _item, name=name: _preset_key(app) == name),
                radio=True,
            )
            for index, (name, label) in enumerate(zip(PRESET_NAMES, PRESET_LABELS, strict=True))
        ]
    )

    vignette_menu = pystray.Menu(
        *[
            pystray.MenuItem(
                label,
                _setter(SET_VIGNETTE, index),
                checked=(lambda _item, strength=strength: _vignette_level(app) == strength),
                radio=True,
            )
            for index, (label, strength) in enumerate(
                zip(VIGNETTE_LABELS, VIGNETTE_LEVELS, strict=True)
            )
        ]
    )

    def _toggle(action: int, current: Callable[[], bool]):
        def _handler(_icon, _item):
            hwnd = app.hwnd
            if hwnd:
                win32.post_app_message(hwnd, APP_SET, action, 0 if current() else 1)

        return _handler

    elements_menu = pystray.Menu(
        pystray.MenuItem(
            "边框",
            _toggle(SET_FRAME, lambda: app.cfg.frame.enabled),
            checked=lambda _item: app.cfg.frame.enabled,
        ),
        pystray.MenuItem(
            "中心准星",
            _toggle(SET_RETICLE, lambda: app.cfg.reticle.enabled),
            checked=lambda _item: app.cfg.reticle.enabled,
        ),
        pystray.MenuItem(
            "锚点阵",
            _toggle(SET_GRID, lambda: app.cfg.grid.enabled),
            checked=lambda _item: app.cfg.grid.enabled,
        ),
        pystray.MenuItem(
            "统计面板",
            _toggle(SET_STATS, lambda: app.cfg.stats.enabled),
            checked=lambda _item: app.cfg.stats.enabled,
        ),
    )

    menu = pystray.Menu(
        pystray.MenuItem("打开控制面板", on_console),
        pystray.MenuItem("显示 / 隐藏叠加层", on_toggle, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("颜色", color_menu),
        pystray.MenuItem("预设", preset_menu),
        pystray.MenuItem("暗角强度", vignette_menu),
        pystray.MenuItem("显示元素", elements_menu),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("重新载入配置", on_reload),
        pystray.MenuItem("打开配置文件夹", on_open_config),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Horizon v{__version__}", None, enabled=False),
        pystray.MenuItem("退出", on_quit),
    )

    icon = pystray.Icon(
        "horizon",
        make_icon_image(app.cfg.color),
        f"Horizon · 3D 眩晕缓解叠加层 v{__version__}",
        menu,
    )
    thread = threading.Thread(target=icon.run, name="horizon-tray", daemon=True)
    thread.start()
    log("[horizon] tray icon started (right-click it to quit)")
    return icon
