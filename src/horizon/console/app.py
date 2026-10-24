"""The control panel window and the API it exposes to the page.

Runs as its own process (``Horizon.exe --console``): pywebview needs the main
thread, and the overlay process is busy pumping a Win32 message loop.

The page never touches the filesystem. Every call goes through this API, which
reads the config, validates the change with ``apply_patch``, and forwards it to
the overlay over ``WM_COPYDATA``. The overlay stays the single writer of
``config.json``; if it is not running we write the file ourselves so the change
is not lost.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .. import ipc
from ..config import HorizonConfig, apply_patch, config_path, load, preset, save
from ..render import mock_frame

UI_DIR = Path(__file__).with_name("ui")
PREVIEW_SIZE = (520, 293)


class Api:
    """Everything the page can call, exposed as ``window.pywebview.api``."""

    def __init__(self, cfg_path: Path | None = None) -> None:
        self._cfg_path = cfg_path or config_path()
        self._window = None
        self._lock = threading.RLock()
        self._temporary_session = False

    # -- helpers -----------------------------------------------------------

    def _load(self) -> HorizonConfig:
        # State/preview requests run on separate WebView threads. They must not
        # reset session provenance while a patch is between read and commit.
        with self._lock:
            hwnd = ipc.find_overlay()
            if hwnd:
                state = ipc.query_state(hwnd)
                if state is None:
                    raise RuntimeError("叠加层未响应，请重试或重新启动叠加层")
                self._temporary_session = bool(state.get("temporary_session"))
                return apply_patch(HorizonConfig(), state["config"])
            self._temporary_session = False
            return load(self._cfg_path)

    def _payload(self, cfg: HorizonConfig, alive: bool) -> dict[str, Any]:
        return {
            "config": cfg.to_dict(),
            "overlay_alive": alive,
            "config_path": str(self._cfg_path),
            "temporary_session": self._temporary_session and alive,
        }

    def _commit(self, cfg: HorizonConfig, changes: dict[str, Any]) -> dict[str, Any]:
        """Forward ``changes`` to the overlay, or persist them if it is down."""
        hwnd = ipc.find_overlay()
        if hwnd:
            if not ipc.send_payload(hwnd, {"patch": changes}):
                raise RuntimeError("叠加层未响应，设置尚未保存，请重试或重新启动叠加层")
        else:
            if self._temporary_session:
                raise RuntimeError("临时会话已结束，设置尚未保存，请刷新后重试")
            save(cfg, self._cfg_path)
        return self._payload(cfg, bool(hwnd))

    # -- exposed methods ---------------------------------------------------

    def state(self) -> dict[str, Any]:
        """Current config plus whether the overlay process is up."""
        with self._lock:
            return self._payload(self._load(), bool(ipc.find_overlay()))

    def patch(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Validate a change, forward it, and return the resulting config."""
        with self._lock:
            current = self._load()
            if isinstance(changes, dict) and "hotkeys" in changes:
                from ..hotkeys import validate_bindings

                if not isinstance(changes["hotkeys"], dict):
                    raise ValueError("快捷键配置必须是对象")
                validate_bindings({**current.hotkeys, **changes["hotkeys"]})
            cfg = apply_patch(current, changes or {})
            if cfg.hotkeys != current.hotkeys and not ipc.find_overlay():
                self._check_hotkeys(cfg)
            return self._commit(cfg, changes or {})

    def _check_hotkeys(self, cfg: HorizonConfig) -> None:
        from .. import win32
        from ..hotkeys import DEFAULT_HOTKEYS, LABELS, parse_binding

        win32.user32.UnregisterHotKey.argtypes = [win32.wintypes.HWND, win32.ctypes.c_int]
        for action, binding in cfg.hotkeys.items():
            if binding == DEFAULT_HOTKEYS[action]:
                continue  # defaults retain the existing fallback-key behaviour
            mods, vk = parse_binding(binding)
            if not win32.register_hotkey(None, 0xBFFE, mods, vk):
                raise ValueError(f"{LABELS[action]}：{binding} 已被其他程序占用")
            win32.user32.UnregisterHotKey(None, 0xBFFE)

    def hotkey_options(self) -> dict[str, Any]:
        from ..hotkeys import LABELS

        return LABELS

    def preset(self, name: str) -> dict[str, Any]:
        """Switch to a named preset, keeping colour and HUD preferences."""
        with self._lock:
            cfg = preset(name, self._load())
            return self._commit(cfg, cfg.to_dict())

    def reset(self) -> dict[str, Any]:
        """Restore every visual parameter to the built-in defaults."""
        with self._lock:
            current = self._load()
            cfg = HorizonConfig()
            cfg.monitor = current.monitor
            cfg.tray_hint_shown = current.tray_hint_shown
            return self._commit(cfg, cfg.to_dict())

    def monitors(self) -> list[dict[str, Any]]:
        """Enumerate monitors so the page can offer a target picker."""
        from ..win32 import list_monitors

        return [
            {"index": index, "width": width, "height": height}
            for index, (_x, _y, width, height) in enumerate(list_monitors())
        ]

    def start_overlay(self) -> dict[str, Any]:
        """Launch the overlay if it is not running, and wait briefly for it."""
        if ipc.find_overlay():
            return self._payload(self._load(), True)
        self._check_hotkeys(self._load())

        from ..launcher import launch

        launch("--overlay", "--config", str(self._cfg_path))

        for _ in range(40):  # up to 10 s: a one-file exe needs to unpack
            time.sleep(0.25)
            if ipc.find_overlay():
                break
        return self._payload(self._load(), bool(ipc.find_overlay()))

    def preview(self, changes: dict[str, Any] | None = None) -> str:
        """Render the mock frame with pending changes applied, as a data URL."""
        cfg = apply_patch(self._load(), changes or {})
        image = mock_frame(cfg, *PREVIEW_SIZE)
        buffer = io.BytesIO()
        image.save(buffer, "PNG", optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def stop_overlay(self) -> dict[str, Any]:
        from .. import win32
        from ..overlay import APP_QUIT

        hwnd = ipc.find_overlay()
        if hwnd:
            win32.post_app_message(hwnd, APP_QUIT)
            for _ in range(40):
                if not ipc.find_overlay():
                    break
                time.sleep(0.1)
        return self.state()

    def toggle_overlay(self) -> dict[str, Any]:
        from .. import win32
        from ..overlay import APP_TOGGLE

        hwnd = ipc.find_overlay()
        if hwnd:
            win32.post_app_message(hwnd, APP_TOGGLE)
        return self.state()

    def import_config(self) -> dict[str, Any] | None:
        import webview

        paths = self._window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("JSON (*.json)",)
        )
        if not paths:
            return None
        raw = json.loads(Path(paths[0]).read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("请选择有效的 Horizon JSON 配置文件")
        raw.pop("tray_hint_shown", None)
        return self.patch(raw)

    def export_config(self) -> str | None:
        import webview

        result = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename="horizon-config.json",
            file_types=("JSON (*.json)",),
        )
        if not result:
            return None
        path = Path(result if isinstance(result, str) else result[0])
        save(self._load(), path)
        return str(path)

    def startup(self, enabled: bool | None = None) -> bool:
        from ..launcher import set_startup, startup_enabled

        if enabled is not None:
            set_startup(bool(enabled))
        return startup_enabled()


def load_html() -> str:
    """Inline the UI into a single document.

    Loading from ``file://`` fails when the project lives on a path with
    non-ASCII characters (which this one does), so the stylesheet and script are
    concatenated into the document instead of being fetched.
    """
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="style.css" />', f"<style>\n{css}\n</style>")
    html = html.replace('<script src="app.js"></script>', f"<script>\n{js}\n</script>")
    return html


def prepare_webview_env() -> None:
    """Apply an explicitly requested WebView2 workaround.

    On machines where the GPU process cannot composite (virtual machines, some
    remote sessions, certain driver/WebView2 combinations) the page loads and
    ``evaluate_js`` works, but nothing is ever painted -- the window stays
    black. Running the GPU thread inside the browser process fixes it.

    Set ``HORIZON_WEBVIEW_ARGS=--in-process-gpu`` on affected machines.
    Leave WebView2's process isolation intact by default.
    """
    override = os.environ.get("HORIZON_WEBVIEW_ARGS")
    if override is not None:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = override


def run(cfg_path: Path | None = None) -> int:
    from ..launcher import single_instance

    with single_instance("console") as unique:
        if not unique:
            from ctypes import wintypes

            from ..win32 import user32

            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            hwnd = user32.FindWindowW(None, "Horizon 控制台")
            if hwnd:
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
            return 0
        return _run_window(cfg_path)


def install_close_guard(window) -> None:
    """Finish the last queued slider edit before closing the panel."""
    state = {"closing": False, "allow": False}

    def closing():
        if state["allow"]:
            return True
        if not window.events.loaded.is_set():
            return True
        if state["closing"]:
            return False
        state["closing"] = True

        def finish():
            complete = threading.Event()
            result = []

            def done(value):
                result.append(value)
                complete.set()

            try:
                window.evaluate_js(
                    "flushPatch().then(() => true).catch(() => false)", callback=done
                )
                if complete.wait(5) and result == [True]:
                    state["allow"] = True
                    window.destroy()
                else:
                    state["closing"] = False
            except Exception:
                state["closing"] = False

        threading.Thread(target=finish, daemon=True).start()
        return False

    window.events.closing += closing


def _run_window(cfg_path: Path | None = None) -> int:
    """Open the control panel and block until the window is closed."""
    try:
        import webview
    except ImportError:
        print("控制台需要 pywebview：pip install pywebview", file=sys.stderr)
        return 2

    missing = [
        name for name in ("index.html", "style.css", "app.js") if not (UI_DIR / name).exists()
    ]
    if missing:  # pragma: no cover - packaging problem
        print(f"控制台页面缺失：{', '.join(missing)}（{UI_DIR}）", file=sys.stderr)
        return 2

    prepare_webview_env()

    api = Api(cfg_path)
    window = webview.create_window(
        "Horizon 控制台",
        html=load_html(),
        js_api=api,
        width=1000,
        height=720,
        min_size=(860, 600),
        background_color="#0d0f12",
    )
    api._window = window
    install_close_guard(window)
    webview.start()
    return 0
