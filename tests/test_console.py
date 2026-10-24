import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows panel and IPC integration", allow_module_level=True)

from horizon import ipc
from horizon.config import apply_patch, default_config, load, preset
from horizon.console.app import Api


def test_standard_preset_restores_visual_defaults():
    cfg = preset("strong")
    cfg.color = "#FFFFFF"
    cfg.session.minutes = 75
    restored = preset("standard", cfg)
    assert restored.vignette.strength == 0.55
    assert restored.frame.width == 8
    assert restored.color == "#FFFFFF"
    assert restored.session.minutes == 75


@pytest.mark.parametrize(
    "changes",
    [
        {"frame": None},
        {"vignette": "bad"},
        {"frame": {"width": float("inf")}},
        {"stats": {"position": []}},
        {"monitor": -4},
    ],
)
def test_invalid_patch_stays_renderable(changes):
    cfg = apply_patch(default_config(), changes)
    assert cfg.frame.width >= 1
    assert cfg.monitor >= 0
    assert cfg.stats.position == "top-left"


def test_invalid_numeric_patch_keeps_custom_value():
    cfg = default_config()
    cfg.frame.width = 17
    assert apply_patch(cfg, {"frame": {"width": "oops"}}).frame.width == 17


def test_rejected_ipc_does_not_report_success(tmp_path, monkeypatch):
    api = Api()
    api._cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(ipc, "find_overlay", lambda: 123)
    monkeypatch.setattr(ipc, "send_payload", lambda *args: False)
    with pytest.raises(RuntimeError, match="响应"):
        api.patch({"color": "#FFFFFF"})
    assert not api._cfg_path.exists()


def test_offline_changes_persist(tmp_path, monkeypatch):
    api = Api()
    api._cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(ipc, "find_overlay", lambda: 0)
    state = api.patch({"frame": {"width": 12}})
    assert state["config"]["frame"]["width"] == load(api._cfg_path).frame.width == 12


def test_load_malformed_sections(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"frame": null, "stats": {"position": []}}')
    assert load(path).frame.width == default_config().frame.width


def test_defaults_match_selected_settings():
    cfg = default_config()
    assert (cfg.vignette.inner, cfg.vignette.outer, cfg.vignette.strength) == (0.34, 1.06, 0.55)
    assert (cfg.frame.inset, cfg.frame.width, cfg.frame.alpha) == (26, 8, 90)
    assert (cfg.reticle.size, cfg.reticle.gap, cfg.reticle.alpha) == (9, 9, 150)
    assert (cfg.session.minutes, cfg.session.reminder_seconds) == (60, 3)
    assert cfg.stats.font_size == 21
    assert not cfg.tray_hint_shown


def test_selected_three_second_reminder_duration(monkeypatch):
    from horizon.overlay import HorizonApp

    app = HorizonApp(default_config())
    app._session_start = 0
    monkeypatch.setattr("horizon.overlay.time.monotonic", lambda: 3601)
    monkeypatch.setattr(app, "redraw", lambda **kwargs: None)
    app._tick_session()
    assert app._notice_until == 3604


def test_console_uses_requested_config(tmp_path):
    path = tmp_path / "custom.json"
    api = Api(path)
    assert api._cfg_path == path


def test_launch_defaults_to_panel(monkeypatch):
    from horizon import __main__, console

    monkeypatch.setattr(console, "run_console", lambda **kwargs: 37)
    assert __main__.main([]) == 37


def test_stopping_overlay_removes_tray_icon():
    from types import SimpleNamespace

    from horizon.overlay import HorizonApp

    stopped = []
    app = HorizonApp(default_config())
    app._tray = SimpleNamespace(stop=lambda: stopped.append(True))
    app._teardown()
    assert stopped == [True]


def test_frozen_children_have_independent_runtime(monkeypatch):
    from horizon import launcher

    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    captured = {}

    def spawn(args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    launcher.launch("--overlay")
    assert captured["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_import_export_roundtrip(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(ipc, "find_overlay", lambda: 0)
    imported = tmp_path / "import.json"
    exported = tmp_path / "export.json"
    imported.write_text(json.dumps({"color": "#ABCDEF", "frame": {"width": 19}}))
    api = Api(tmp_path / "active.json")

    class Dialog:
        def create_file_dialog(self, kind, **kwargs):
            return [str(imported)] if "save_filename" not in kwargs else str(exported)

    api._window = Dialog()
    assert api.import_config()["config"]["frame"]["width"] == 19
    assert api.export_config() == str(exported)
    assert load(exported).color == "#ABCDEF"
    imported.write_text("[]")
    with pytest.raises(ValueError):
        api.import_config()
    assert load(api._cfg_path).frame.width == 19


def test_triangles_panel_persistence_preview_and_reset(tmp_path, monkeypatch):
    import base64
    import io

    from PIL import Image

    monkeypatch.setattr(ipc, "find_overlay", lambda: 0)
    api = Api(tmp_path / "config.json")
    initial_preview = api.preview()
    settings = {
        "enabled": True,
        "filled": True,
        "base": 65.0,
        "depth": 27.0,
        "width": 8,
        "alpha": 102,
    }
    state = api.patch({"triangles": settings})
    assert state["config"]["triangles"] == settings
    assert api.preview() != initial_preview
    hollow = api.preview({"triangles": {"filled": False}})
    assert Image.open(io.BytesIO(base64.b64decode(hollow.split(",", 1)[1]))).width > 0
    assert load(api._cfg_path).triangles.filled
    assert api.preset("strong")["config"]["triangles"] == settings
    assert api.reset()["config"]["triangles"] == default_config().to_dict()["triangles"]


def test_triangle_import_export_preserves_mode_and_dimensions(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(ipc, "find_overlay", lambda: 0)
    imported = tmp_path / "triangles.json"
    exported = tmp_path / "exported.json"
    settings = {
        "enabled": True,
        "filled": True,
        "base": 68.0,
        "depth": 33.0,
        "width": 7,
        "alpha": 81,
    }
    imported.write_text(json.dumps({"triangles": settings}))
    api = Api(tmp_path / "active.json")

    class Dialog:
        def create_file_dialog(self, kind, **kwargs):
            return str(exported) if "save_filename" in kwargs else [str(imported)]

    api._window = Dialog()
    assert api.import_config()["config"]["triangles"] == settings
    api.export_config()
    assert load(exported).to_dict()["triangles"] == settings


def test_ipc_timeout_does_not_claim_hotkey_conflict(tmp_path, monkeypatch):
    api = Api(tmp_path / "config.json")
    monkeypatch.setattr(ipc, "find_overlay", lambda: 123)
    monkeypatch.setattr(ipc, "send_payload", lambda *args: False)
    with pytest.raises(RuntimeError) as error:
        api.patch({"frame": {"width": 12}})
    assert "未响应" in str(error.value)
    assert "快捷键" not in str(error.value)


def test_patch_reads_configuration_once(tmp_path, monkeypatch):
    api = Api(tmp_path / "config.json")
    reads = []

    def read():
        reads.append(True)
        return default_config()

    monkeypatch.setattr(api, "_load", read)
    monkeypatch.setattr(ipc, "find_overlay", lambda: 0)
    state = api.patch({"frame": {"width": 12}})
    assert state["config"]["frame"]["width"] == 12
    assert len(reads) == 1


def test_gpu_workaround_is_opt_in(monkeypatch):
    from horizon.console.app import prepare_webview_env

    monkeypatch.delenv("HORIZON_WEBVIEW_ARGS", raising=False)
    monkeypatch.delenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", raising=False)
    prepare_webview_env()
    assert "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS" not in __import__("os").environ


def test_gpu_workaround_accepts_explicit_override(monkeypatch):
    from horizon.console.app import prepare_webview_env

    monkeypatch.setenv("HORIZON_WEBVIEW_ARGS", "--in-process-gpu")
    prepare_webview_env()
    assert __import__("os").environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] == "--in-process-gpu"


def test_ipc_reports_hotkey_rejection_separately(monkeypatch):
    def deliver(hwnd, msg, wparam, address, flags, timeout, result):
        result._obj.value = 2
        return 1

    monkeypatch.setattr(ipc.user32, "SendMessageTimeoutW", deliver)
    with pytest.raises(ValueError, match="快捷键"):
        ipc.send_payload(123, {"patch": {"hotkeys": {"quit": "Ctrl+Shift+9"}}})


def test_temporary_overlay_exit_during_edit_never_persists_overrides(tmp_path, monkeypatch):
    from horizon.config import save

    path = tmp_path / "config.json"
    save(default_config(), path)
    original = path.read_bytes()
    temporary = default_config()
    temporary.color = "#ABCDEF"
    handles = iter([123, 0])
    monkeypatch.setattr(ipc, "find_overlay", lambda: next(handles))
    monkeypatch.setattr(
        ipc, "query_state", lambda _: {"config": temporary.to_dict(), "temporary_session": True}
    )
    api = Api(path)
    with pytest.raises(RuntimeError, match="临时会话"):
        api.patch({"frame": {"width": 12}})
    assert path.read_bytes() == original


@pytest.mark.parametrize("operation", ["patch", "preset", "reset"])
def test_concurrent_poll_cannot_make_temporary_edit_persistent(tmp_path, monkeypatch, operation):
    import threading

    from horizon.config import save

    path = tmp_path / "config.json"
    save(default_config(), path)
    original = path.read_bytes()
    temporary = default_config()
    temporary.color = "#ABCDEF"
    temporary.monitor = 1
    handles = iter([123])
    monkeypatch.setattr(ipc, "find_overlay", lambda: next(handles, 0))
    monkeypatch.setattr(
        ipc, "query_state", lambda _: {"config": temporary.to_dict(), "temporary_session": True}
    )
    api = Api(path)
    editing, polling, polled = threading.Event(), threading.Event(), threading.Event()
    commit = api._commit
    errors = []

    def paused_commit(cfg, changes):
        editing.set()
        assert polling.wait(2)
        polled.wait(0.2)  # an unsynchronized poll can reset the session flag here
        return commit(cfg, changes)

    def edit():
        try:
            if operation == "patch":
                api.patch({"frame": {"width": 12}})
            elif operation == "preset":
                api.preset("strong")
            else:
                api.reset()
        except RuntimeError as exc:
            errors.append(str(exc))

    def poll():
        assert editing.wait(2)
        polling.set()
        api.state()
        polled.set()

    monkeypatch.setattr(api, "_commit", paused_commit)
    editor, observer = threading.Thread(target=edit), threading.Thread(target=poll)
    editor.start()
    observer.start()
    editor.join(3)
    observer.join(3)
    assert not editor.is_alive() and not observer.is_alive()
    assert path.read_bytes() == original
    assert len(errors) == 1 and "临时会话" in errors[0]
