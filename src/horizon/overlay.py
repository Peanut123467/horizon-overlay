"""The overlay application: window lifecycle, hotkeys, session timer, HUD.

Design constraints that shaped this file:

* **No per-frame work.** The overlay is static, so we recompose only when a
  parameter or the notice text changes. A full-screen 32-bit blit every frame
  would itself cost real bandwidth and could worsen frame pacing.
* **The HUD lives in its own window.** A full-screen recomposition costs ~60 ms
  at 1080p and ~108 ms at 1440p; doing that once a second just to update a
  memory number would burn ~10% of a core. The stats panel is a ~300x30 layered
  window instead, so refreshing it is essentially free.
* **Never touch the game.** No process handle, no injection, no file access
  outside our own config.
* **Never steal focus.** ``WS_EX_NOACTIVATE`` + ``SW_SHOWNOACTIVATE``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from . import metrics, win32
from .config import COLOR_PALETTE, HorizonConfig, next_color, preset, save
from .render import compose, compose_stats

__all__ = ["HorizonApp"]

# virtual-key codes
VK = {
    "H": 0x48,
    "Q": 0x51,
    "T": 0x54,
    "S": 0x53,
    "C": 0x43,
    "1": 0x31,
    "2": 0x32,
    "3": 0x33,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}

TIMER_WATCHDOG = 1
TIMER_SESSION = 2
TIMER_AUTOQUIT = 3
TIMER_STATS = 4
TIMER_HINT = 5

HOTKEY_TOGGLE = 1
HOTKEY_GENTLE = 2
HOTKEY_STANDARD = 3
HOTKEY_STRONG = 4
HOTKEY_RETICLE = 5
HOTKEY_QUIT = 6
HOTKEY_STATS = 7
HOTKEY_COLOR = 8

# Each action lists candidate keys in order of preference. The first one that
# Windows actually grants wins -- another app may already own Ctrl+Alt+T, and
# we would rather fall back than lose the action entirely.
HOTKEY_BINDINGS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (HOTKEY_TOGGLE, "显示/隐藏", ("H", "F9")),
    (HOTKEY_GENTLE, "轻微", ("1", "F7")),
    (HOTKEY_STANDARD, "标准", ("2", "F8")),
    (HOTKEY_STRONG, "强", ("3",)),
    (HOTKEY_RETICLE, "准星", ("T", "F10")),
    (HOTKEY_STATS, "统计面板", ("S", "F11")),
    (HOTKEY_COLOR, "切换颜色", ("C", "F12")),
    (HOTKEY_QUIT, "退出", ("Q",)),
)

# WM_APP offsets used by the tray thread
APP_TOGGLE = 1
APP_QUIT = 2
APP_RELOAD = 3
APP_SET = 4  # wparam = SET_* action, lparam = value

# Settings the tray menu can change. The tray thread only posts these codes; the
# overlay thread owns the config, so there is exactly one writer.
SET_COLOR = 1
SET_PRESET = 2
SET_VIGNETTE = 3
SET_FRAME = 4
SET_RETICLE = 5
SET_GRID = 6
SET_STATS = 7

# index -> vignette strength. 0 disables the vignette entirely.
VIGNETTE_LEVELS: tuple[float, ...] = (0.0, 0.35, 0.55, 0.78)
VIGNETTE_LABELS: tuple[str, ...] = ("关闭", "轻", "中", "强")

PRESET_NAMES: tuple[str, ...] = ("gentle", "standard", "strong")
PRESET_LABELS: tuple[str, ...] = ("轻微", "标准", "强")


def apply_setting(cfg: HorizonConfig, action: int, value: int) -> HorizonConfig | None:
    """Apply a tray-menu action to ``cfg``.

    Pure config mutation -- no windows, no I/O -- so it can be tested directly.
    Returns the (possibly replaced) config, or ``None`` for an unknown action.
    """
    if action == SET_COLOR:
        cfg.color = COLOR_PALETTE[value % len(COLOR_PALETTE)]
    elif action == SET_PRESET:
        if not 0 <= value < len(PRESET_NAMES):
            return None
        return preset(PRESET_NAMES[value], cfg)
    elif action == SET_VIGNETTE:
        level = max(0, min(value, len(VIGNETTE_LEVELS) - 1))
        strength = VIGNETTE_LEVELS[level]
        cfg.vignette.enabled = strength > 0
        cfg.vignette.strength = strength
    elif action == SET_FRAME:
        cfg.frame.enabled = bool(value)
    elif action == SET_RETICLE:
        cfg.reticle.enabled = bool(value)
    elif action == SET_GRID:
        cfg.grid.enabled = bool(value)
    elif action == SET_STATS:
        cfg.stats.enabled = bool(value)
    else:
        return None
    return cfg


class _Layer:
    """One layered window plus its backing DIB."""

    def __init__(self, rect: tuple[int, int, int, int], wndproc, title: str) -> None:
        x, y, w, h = rect
        self.rect = rect
        self.hwnd = win32.create_overlay_window(x, y, w, h, wndproc, title=title)
        self.surface = win32.LayeredSurface(w, h)

    def present(self, bgra: bytes) -> None:
        self.surface.blit(bgra)
        win32.present(self.hwnd, self.surface, self.rect[0], self.rect[1])

    def place(self, rect: tuple[int, int, int, int]) -> None:
        """Move and/or resize, recreating the DIB only when the size changed."""
        if rect == self.rect:
            return
        x, y, w, h = rect
        if (w, h) != (self.rect[2], self.rect[3]):
            self.surface.release()
            self.surface = win32.LayeredSurface(w, h)
        win32.resize(self.hwnd, x, y, w, h)
        self.rect = rect

    def release(self) -> None:
        self.surface.release()


class HorizonApp:
    """Owns the overlay windows and the message loop."""

    def __init__(
        self,
        cfg: HorizonConfig,
        cfg_path: Path | None = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.log = log

        self.main: _Layer | None = None
        self.hud: _Layer | None = None
        self.geometry: tuple[int, int, int, int] = (0, 0, 0, 0)

        self._wndproc = None  # must stay referenced while windows live
        self._tray = None
        self.hotkey_map: dict[int, str] = {}

        self._visible = not cfg.start_hidden
        self._render_key: str | None = None
        self._draw_ms = 0.0
        self._hud_last_text: str | None = None
        self._session_start = time.monotonic()
        self._reminded = False
        self._notice_until = 0.0
        self._hint_until = 0.0

    @property
    def hwnd(self):
        """The main overlay window (kept for the tray/back-compat)."""
        return self.main.hwnd if self.main else None

    # ------------------------------------------------------------- lifecycle

    def run(self, duration: float | None = None, with_tray: bool = True) -> None:
        win32.set_dpi_aware()
        self._create()
        if with_tray:
            from .tray import start_tray

            self._tray = start_tray(self, self.log)
            self._maybe_show_tray_hint()
        if duration:
            win32.set_timer(self.hwnd, TIMER_AUTOQUIT, int(duration * 1000))
        win32.run_message_loop()
        self._teardown()

    def _create(self) -> None:
        monitors = win32.list_monitors()
        idx = min(max(self.cfg.monitor, 0), len(monitors) - 1)
        self.geometry = monitors[idx]

        self._wndproc = win32.WNDPROC(self._on_message)
        self.main = _Layer(self.geometry, self._wndproc, "Horizon Overlay")
        self._register_hotkeys()

        win32.show(self.main.hwnd)
        win32.reassert_topmost(self.main.hwnd)
        self.redraw(force=True)
        # Second pass purely to get an honest "重绘" number for the HUD: the
        # first compose includes font loading and numpy warm-up and reads
        # roughly 2x the steady-state cost.
        self.redraw(force=True)
        self._sync_hud()

        win32.set_timer(self.main.hwnd, TIMER_WATCHDOG, 2000)
        win32.set_timer(self.main.hwnd, TIMER_SESSION, 10_000)
        x, y, w, h = self.geometry
        self.log(f"[horizon] overlay on monitor {idx} ({w}x{h} at {x},{y})")

    def _register_hotkeys(self) -> None:
        mods = win32.MOD_CONTROL | win32.MOD_ALT
        self.hotkey_map = {}
        for hotkey_id, label, candidates in HOTKEY_BINDINGS:
            for name in candidates:
                if win32.register_hotkey(self.main.hwnd, hotkey_id, mods, VK[name]):
                    self.hotkey_map[hotkey_id] = name
                    self.log(f"[horizon] hotkey: Ctrl+Alt+{name}  {label}")
                    break
            else:
                self.log(f"[horizon] hotkey unavailable for '{label}' (all candidates taken)")

    def _maybe_show_tray_hint(self) -> None:
        """First run: point at the tray icon *on the overlay itself*.

        A tray balloon would be the obvious choice, but Windows can suppress
        notifications (Focus Assist, notification settings, no toast support),
        and we would never know. These are our own pixels, so this always shows.
        """
        if self.cfg.tray_hint_shown or self.main is None:
            return
        self.cfg.tray_hint_shown = True
        self._persist()
        self._hint_until = time.monotonic() + 8.0
        win32.set_timer(self.main.hwnd, TIMER_HINT, 1000)
        self.redraw(force=True)
        self.log("[horizon] first-run tray hint shown on the overlay")

    def _teardown(self) -> None:
        for layer in (self.hud, self.main):
            if layer is not None:
                layer.release()
        self.hud = None
        self.main = None

    # -------------------------------------------------------------- messages

    def _on_message(self, hwnd, msg, wparam, lparam):
        try:
            return self._dispatch(hwnd, msg, wparam, lparam)
        except Exception as exc:  # never let an exception unwind into C
            self.log(f"[horizon] error handling message {msg:#x}: {exc!r}")
            return 0

    def _dispatch(self, hwnd, msg, wparam, lparam):
        if msg == win32.WM_HOTKEY:
            self._on_hotkey(int(wparam))
            return 0
        if msg == win32.WM_TIMER:
            self._on_timer(int(wparam))
            return 0
        if msg == win32.WM_DISPLAYCHANGE:
            self._on_display_change()
            return 0
        if msg == win32.WM_APP + APP_TOGGLE:
            self.toggle()
            return 0
        if msg == win32.WM_APP + APP_RELOAD:
            self.reload_config()
            return 0
        if msg == win32.WM_APP + APP_SET:
            self._apply_setting(int(wparam), int(lparam))
            return 0
        if msg == win32.WM_APP + APP_QUIT:
            win32.destroy_window(self.hwnd)
            return 0
        if msg == win32.WM_CLOSE:
            win32.destroy_window(hwnd)
            return 0
        if msg == win32.WM_DESTROY:
            if hwnd == self.hwnd:
                win32.post_quit()
            return 0
        return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _on_hotkey(self, hotkey_id: int) -> None:
        if hotkey_id == HOTKEY_TOGGLE:
            self.toggle()
            return
        if hotkey_id == HOTKEY_QUIT:
            win32.destroy_window(self.hwnd)
            return
        if hotkey_id == HOTKEY_RETICLE:
            self.cfg.reticle.enabled = not self.cfg.reticle.enabled
        elif hotkey_id == HOTKEY_STATS:
            self.cfg.stats.enabled = not self.cfg.stats.enabled
        elif hotkey_id == HOTKEY_COLOR:
            self.cfg.color = next_color(self.cfg.color)
            self.log(f"[horizon] colour -> {self.cfg.color}")
            from .tray import refresh_icon

            refresh_icon(self._tray, self.cfg.color)
        elif hotkey_id in (HOTKEY_GENTLE, HOTKEY_STANDARD, HOTKEY_STRONG):
            name = {HOTKEY_GENTLE: "gentle", HOTKEY_STANDARD: "standard", HOTKEY_STRONG: "strong"}[
                hotkey_id
            ]
            self.cfg = preset(name, self.cfg)
            self.log(f"[horizon] preset -> {name}")
        self._persist()
        self.redraw(force=True)
        self._sync_hud()

    def _on_timer(self, timer_id: int) -> None:
        if timer_id == TIMER_WATCHDOG:
            if self._visible:
                win32.reassert_topmost(self.hwnd)
                if self.hud is not None:
                    win32.reassert_topmost(self.hud.hwnd)
        elif timer_id == TIMER_SESSION:
            self._tick_session()
        elif timer_id == TIMER_STATS:
            self._refresh_hud()
        elif timer_id == TIMER_HINT:
            if time.monotonic() >= self._hint_until:
                self._hint_until = 0.0
                win32.kill_timer(self.main.hwnd, TIMER_HINT)
                self.redraw(force=True)
        elif timer_id == TIMER_AUTOQUIT:
            win32.destroy_window(self.hwnd)

    def _on_display_change(self) -> None:
        """Resolution/monitor change: rebuild both surfaces at the new size."""
        try:
            monitors = win32.list_monitors()
            idx = min(max(self.cfg.monitor, 0), len(monitors) - 1)
            rect = monitors[idx]
            if rect == self.geometry:
                return
            self.geometry = rect
            self.main.place(rect)
            self.redraw(force=True)
            self._sync_hud()
            self.log(f"[horizon] display changed -> {rect[2]}x{rect[3]}")
        except Exception as exc:
            self.log(f"[horizon] display-change recovery failed: {exc!r}")

    # --------------------------------------------------------------- session

    def _tick_session(self) -> None:
        now = time.monotonic()

        if self._notice_until and now >= self._notice_until:
            self._notice_until = 0.0
            self._session_start = now
            self._reminded = False
            self.redraw(force=True)
            return

        s = self.cfg.session
        if not s.enabled or self._reminded or not self._visible:
            return
        if now - self._session_start >= s.minutes * 60:
            self._reminded = True
            self._notice_until = now + max(5, s.reminder_seconds)
            self.redraw(force=True)

    def _notice_text(self) -> str | None:
        now = time.monotonic()
        if self._hint_until and now < self._hint_until:
            return "Horizon 已启动 · 图标在右下角托盘，右键可退出"
        if not self._notice_until or now >= self._notice_until:
            return None
        return f"已连续游玩 {self.cfg.session.minutes} 分钟 · 建议起身活动 1–2 分钟"

    # ----------------------------------------------------------------- paint

    def toggle(self) -> None:
        self._visible = not self._visible
        layers = [layer for layer in (self.main, self.hud) if layer is not None]
        if self._visible:
            for layer in layers:
                win32.show(layer.hwnd)
                win32.reassert_topmost(layer.hwnd)
            self.redraw(force=True)
            self._sync_hud()
        else:
            for layer in layers:
                win32.hide(layer.hwnd)
        self.log(f"[horizon] overlay {'shown' if self._visible else 'hidden'}")

    def redraw(self, force: bool = False) -> None:
        if self.main is None or not self._visible:
            return
        notice = self._notice_text()
        key = json.dumps(
            {"cfg": self.cfg.to_dict(), "notice": notice}, sort_keys=True, ensure_ascii=False
        )
        if not force and key == self._render_key:
            return

        _, _, w, h = self.main.rect
        started = time.perf_counter()
        self.main.present(compose(self.cfg, w, h, notice))
        self._draw_ms = (time.perf_counter() - started) * 1000
        self._render_key = key

    # ------------------------------------------------------------------- hud

    def _hud_rect(self, w: int, h: int) -> tuple[int, int, int, int]:
        gx, gy, gw, gh = self.geometry
        margin = max(6, self.cfg.frame.inset) + 14
        pos = self.cfg.stats.position or "top-left"
        x = gx + margin if "left" in pos else gx + gw - margin - w
        y = gy + margin if "top" in pos else gy + gh - margin - h
        return (x, y, w, h)

    def _sync_hud(self) -> None:
        """Create, update, or remove the HUD to match the current config."""
        if not self._visible:
            return

        if not self.cfg.stats.enabled:
            if self.hud is not None:
                win32.destroy_window(self.hud.hwnd)
                self.hud.release()
                self.hud = None
            return

        text = self._hud_text()
        bgra, w, h = compose_stats(self.cfg, text)

        if self.hud is None:
            self.hud = _Layer(self._hud_rect(w, h), self._wndproc, "Horizon HUD")
            win32.show(self.hud.hwnd)
            win32.set_timer(self.hud.hwnd, TIMER_STATS, max(250, self.cfg.stats.refresh_ms))
        else:
            self.hud.place(self._hud_rect(w, h))

        self.hud.present(bgra)
        self._hud_last_text = text
        win32.reassert_topmost(self.hud.hwnd)

    def _refresh_hud(self) -> None:
        if self.hud is None or not self.cfg.stats.enabled:
            return
        text = self._hud_text()
        if text == self._hud_last_text:
            return
        bgra, w, h = compose_stats(self.cfg, text)
        self.hud.place(self._hud_rect(w, h))
        self.hud.present(bgra)
        self._hud_last_text = text

    def _hud_text(self) -> str:
        return metrics.snapshot(self._draw_ms).render()

    # ----------------------------------------------------------------- state

    def _apply_setting(self, action: int, value: int) -> None:
        """Apply a change requested by the tray menu.

        The tray thread never mutates the config; it posts ``APP_SET`` and this
        method -- on the overlay thread -- is the single writer.
        """
        updated = apply_setting(self.cfg, action, value)
        if updated is None:
            return
        self.cfg = updated

        if action == SET_COLOR:
            from .tray import refresh_icon

            refresh_icon(self._tray, self.cfg.color)

        self._persist()
        self.redraw(force=True)
        self._sync_hud()

    def reload_config(self) -> None:
        """Re-read the config file and apply it without restarting."""
        if self.cfg_path is None:
            return
        from .config import load

        try:
            fresh = load(self.cfg_path)
        except Exception as exc:  # defensive: load() already swallows most cases
            self.log(f"[horizon] reload failed: {exc!r}")
            return
        # Keep the monitor actually in use; changing it needs a rebuild.
        fresh.monitor = self.cfg.monitor
        self.cfg = fresh
        self._render_key = None
        self.redraw(force=True)
        self._sync_hud()
        from .tray import refresh_icon

        refresh_icon(self._tray, self.cfg.color)
        self.log("[horizon] config reloaded from disk")

    def _persist(self) -> None:
        if self.cfg_path is None:
            return
        try:
            save(self.cfg, self.cfg_path)
        except OSError as exc:
            self.log(f"[horizon] could not save config: {exc!r}")
