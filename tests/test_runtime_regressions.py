import ctypes
import sys
from types import SimpleNamespace

import pytest

if sys.platform != "win32":
    pytest.skip("Windows runtime integration", allow_module_level=True)

from horizon import hotkeys, ipc, overlay, win32
from horizon.config import default_config, save


def layer(hwnd, events):
    return SimpleNamespace(
        hwnd=hwnd,
        release=lambda: events.append(("release", hwnd)),
    )


def test_teardown_unregisters_hotkeys_and_destroys_both_windows(monkeypatch):
    events = []
    app = overlay.HorizonApp(default_config())
    app.main = layer(11, events)
    app.hud = layer(12, events)
    app.hotkey_map = {1: "Ctrl+Alt+H"}
    monkeypatch.setattr(win32.user32, "UnregisterHotKey", lambda h, i: events.append(("key", h, i)))
    monkeypatch.setattr(win32, "destroy_window", lambda h: events.append(("destroy", h)))
    app._teardown()
    assert events == [
        ("key", 11, 1),
        ("destroy", 12),
        ("release", 12),
        ("destroy", 11),
        ("release", 11),
    ]
    assert app.hud is app.main is None
    assert not app.hotkey_map


def test_destroyed_hud_is_released_and_never_refreshed(monkeypatch):
    events = []
    app = overlay.HorizonApp(default_config())
    app.main = layer(11, events)
    app.hud = layer(12, events)
    monkeypatch.setattr(win32, "post_quit", lambda: events.append("quit"))
    app._dispatch(12, win32.WM_DESTROY, 0, 0)
    assert app.hud is None
    app._refresh_hud()
    assert events == [("release", 12)]


def test_run_always_cleans_up_when_loop_fails(monkeypatch):
    events = []
    app = overlay.HorizonApp(default_config())
    monkeypatch.setattr(win32, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(app, "_create", lambda: None)
    monkeypatch.setattr(app, "_teardown", lambda: events.append("cleanup"))

    def fail():
        raise RuntimeError("loop failed")

    monkeypatch.setattr(win32, "run_message_loop", fail)
    with pytest.raises(RuntimeError, match="loop failed"):
        app.run(with_tray=False)
    assert events == ["cleanup"]


def test_zero_duration_schedules_immediate_exit(monkeypatch):
    app = overlay.HorizonApp(default_config())
    timers = []
    monkeypatch.setattr(win32, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(app, "_create", lambda: None)
    monkeypatch.setattr(win32, "run_message_loop", lambda: None)
    monkeypatch.setattr(win32, "set_timer", lambda h, i, ms: timers.append((i, ms)))
    app.run(duration=0, with_tray=False)
    assert timers == [(overlay.TIMER_AUTOQUIT, 1)]


def test_reminder_reports_elapsed_time_after_interval_change(monkeypatch):
    app = overlay.HorizonApp(default_config())
    app._session_start = 0
    app.cfg.session.minutes = 10
    monkeypatch.setattr(overlay.time, "monotonic", lambda: 50 * 60)
    monkeypatch.setattr(app, "redraw", lambda **kwargs: None)
    app._tick_session()
    assert "50 分钟" in app._notice_text()


def test_hotkey_registration_does_not_depend_on_default_dictionary_order(monkeypatch):
    app = overlay.HorizonApp(default_config())
    app.main = layer(11, [])
    app.cfg.hotkeys["quit"] = "Ctrl+Shift+9"
    monkeypatch.setattr(hotkeys, "ACTIONS", tuple(reversed(hotkeys.ACTIONS)))
    registrations = {}

    def register(hwnd, key_id, mods, vk):
        registrations[key_id] = (mods, vk)
        return True

    monkeypatch.setattr(win32, "register_hotkey", register)
    app._register_hotkeys()
    assert registrations[overlay.HOTKEY_QUIT] == (6, ord("9"))
    assert registrations[overlay.HOTKEY_TOGGLE] == (3, ord("H"))


def test_hotkey_rejection_ids_do_not_depend_on_action_order(monkeypatch):
    app = overlay.HorizonApp(default_config())
    app.main = layer(11, [])
    monkeypatch.setattr(hotkeys, "ACTIONS", tuple(reversed(hotkeys.ACTIONS)))
    monkeypatch.setattr(
        ipc, "read_payload", lambda _: {"patch": {"hotkeys": {"quit": "Ctrl+Shift+9"}}}
    )
    monkeypatch.setattr(win32, "register_hotkey", lambda h, i, m, v: i != overlay.HOTKEY_QUIT)
    monkeypatch.setattr(win32, "set_timer", lambda *args: None)
    monkeypatch.setattr(app, "_on_display_change", lambda: None)
    original = app.cfg.hotkeys.copy()
    assert app._on_copydata(0) != 1
    assert app.cfg.hotkeys == original


def test_identical_tray_setting_does_not_recompose(monkeypatch):
    app = overlay.HorizonApp(default_config())
    frames = []
    app.main = SimpleNamespace(hwnd=11, rect=(0, 0, 100, 60), present=frames.append)
    monkeypatch.setattr(app, "_sync_hud", lambda: None)
    app.redraw()
    app._apply_setting(overlay.SET_FRAME, 1)
    assert len(frames) == 1


def test_monitors_are_primary_first_even_when_enumerated_last(monkeypatch):
    def enumerate_monitors(hdc, rect, callback, data):
        callback(2, None, None, 0)
        callback(1, None, None, 0)
        return True

    def monitor_info(handle, pointer):
        info = ctypes.cast(pointer, ctypes.POINTER(win32.MONITORINFO)).contents
        info.dwFlags = 1 if handle == 1 else 0
        info.rcMonitor.left = 0 if handle == 1 else 1920
        info.rcMonitor.top = 0
        info.rcMonitor.right = info.rcMonitor.left + 1920
        info.rcMonitor.bottom = 1080
        return True

    monkeypatch.setattr(win32.user32, "EnumDisplayMonitors", enumerate_monitors)
    monkeypatch.setattr(win32.user32, "GetMonitorInfoW", monitor_info)
    assert win32.list_monitors() == [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]


@pytest.mark.parametrize(
    "arguments",
    [["--preset", "strong"], ["--color", "#ABCDEF"], ["--monitor", "1"], ["--no-stats"]],
)
def test_cli_overrides_never_overwrite_saved_settings(tmp_path, monkeypatch, arguments):
    from horizon import __main__, launcher

    path = tmp_path / "config.json"
    save(default_config(), path)
    original = path.read_bytes()
    app_class = overlay.HorizonApp

    def run(app, **kwargs):
        app.cfg.tray_hint_shown = True
        app._persist()

    monkeypatch.setattr(app_class, "run", run)
    monkeypatch.setattr(
        launcher, "single_instance", lambda _: __import__("contextlib").nullcontext(True)
    )
    assert __main__.main(["--overlay", "--config", str(path), *arguments]) == 0
    assert path.read_bytes() == original


def test_cli_invalid_values_are_validated(tmp_path):
    from horizon.__main__ import _resolve_config, build_parser

    args = build_parser().parse_args(
        ["--config", str(tmp_path / "cfg.json"), "--color", "#12345", "--monitor", "-4"]
    )
    cfg, _ = _resolve_config(args)
    assert cfg.color == "#00FF66"
    assert cfg.monitor == 0


def test_temporary_session_panel_edits_use_live_state(tmp_path, monkeypatch):
    from horizon.console.app import Api

    path = tmp_path / "config.json"
    save(default_config(), path)
    original = path.read_bytes()
    app = overlay.HorizonApp(default_config(), path, persist_config=False)
    app.main = layer(11, [])
    app.cfg.color = "#ABCDEF"
    monkeypatch.setattr(win32, "set_timer", lambda *args: None)
    monkeypatch.setattr(app, "_on_display_change", lambda: None)
    monkeypatch.setattr(ipc, "find_overlay", lambda: 11)

    def send(hwnd, payload, tag=ipc.TAG_PATCH):
        monkeypatch.setattr(ipc, "read_payload", lambda _: payload)
        return app._on_copydata(0) == 1

    monkeypatch.setattr(ipc, "send_payload", send)
    api = Api(path)
    assert api.state()["config"]["color"] == "#ABCDEF"
    assert api.state()["temporary_session"] is True
    assert api.patch({"frame": {"width": 12}})["config"]["frame"]["width"] == 12
    assert api.patch({"frame": {"alpha": 100}})["config"]["frame"]["width"] == 12
    assert api.state()["config"]["frame"]["width"] == app.cfg.frame.width == 12
    assert path.read_bytes() == original


def test_apply_timer_does_not_erase_previous_patch_backup(tmp_path, monkeypatch):
    from horizon.config import load

    path = tmp_path / "config.json"
    save(default_config(), path)
    app = overlay.HorizonApp(default_config(), path)
    app.main = layer(11, [])
    monkeypatch.setattr(ipc, "read_payload", lambda _: {"patch": {"color": "#ABCDEF"}})
    monkeypatch.setattr(win32, "set_timer", lambda *args: None)
    monkeypatch.setattr(win32, "kill_timer", lambda *args: None)
    monkeypatch.setattr(app, "_on_display_change", lambda: None)
    monkeypatch.setattr(app, "redraw", lambda **kwargs: None)
    monkeypatch.setattr(app, "_sync_hud", lambda: None)
    assert app._on_copydata(0) == 1
    app._on_timer(overlay.TIMER_APPLY)
    assert load(path).color == "#ABCDEF"
    assert load(path.with_name("config.json.bak")).color == "#00FF66"
