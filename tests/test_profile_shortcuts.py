import json
import sys
from types import SimpleNamespace

import pytest

from horizon.config import HorizonConfig, apply_patch, load, save
from horizon.profiles import ProfileStore, visual_settings


@pytest.fixture
def store(tmp_path):
    result = ProfileStore(tmp_path / "profiles.json")
    result.save("探索", HorizonConfig())
    return result


def test_share_roundtrip_has_no_machine_settings_and_new_identity(store, tmp_path):
    original = store.list()[0]
    path = tmp_path / "share.json"
    store.export_file(original["id"], path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) == {"format", "version", "name", "visuals"}
    assert raw["visuals"] == original["visuals"]
    store.import_file(path)
    imported = store.list()[1]
    assert imported["id"] != original["id"]
    assert imported["name"] == "探索 · 导入 1"
    assert imported["visuals"] == original["visuals"]


@pytest.mark.parametrize(
    "bad",
    [b"garbage", b"[]", b"\xff", b" " * (256 * 1024 + 1)],
    ids=["json", "shape", "encoding", "size"],
)
def test_bad_share_keeps_library(store, tmp_path, bad):
    before = store.path.read_bytes()
    path = tmp_path / "bad.json"
    path.write_bytes(bad)
    with pytest.raises(ValueError):
        store.import_file(path)
    assert store.path.read_bytes() == before


def test_share_rejects_extra_fields_and_invalid_visuals(store, tmp_path):
    path = tmp_path / "share.json"
    store.export_file(store.list()[0]["id"], path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    before = store.path.read_bytes()
    raw["hotkeys"] = {"toggle": "Ctrl+J"}
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        store.import_file(path)
    del raw["hotkeys"]
    raw["visuals"]["frame"]["width"] = -99
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        store.import_file(path)
    assert store.path.read_bytes() == before


def test_long_duplicate_names_and_capacity(store, tmp_path):
    identifier = store.list()[0]["id"]
    store.rename(identifier, "长" * 40)
    path = tmp_path / "share.json"
    store.export_file(identifier, path)
    for _ in range(49):
        store.import_file(path)
    entries = store.list()
    assert len({p["id"] for p in entries}) == 50
    assert len({p["name"] for p in entries}) == 50
    assert all(len(p["name"]) <= 40 for p in entries)
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="50"):
        store.import_file(path)
    assert store.path.read_bytes() == before


def test_profile_bindings_config_roundtrip_and_clear(tmp_path):
    cfg = apply_patch(HorizonConfig(), {"profile_hotkeys": {"abc": "Ctrl+Alt+J"}})
    assert cfg.profile_hotkeys == {"abc": "Ctrl+Alt+J"}
    path = tmp_path / "config.json"
    save(cfg, path)
    assert load(path).profile_hotkeys == cfg.profile_hotkeys
    cleared = apply_patch(cfg, {"profile_hotkeys": {"abc": ""}})
    assert cleared.profile_hotkeys == {}


def test_profile_bindings_reject_duplicate_and_fixed_conflicts():
    from horizon.hotkeys import validate_profile_bindings

    for bindings in ({"a": "Ctrl+Alt+H"}, {"a": "Ctrl+J", "b": "Ctrl+J"}):
        with pytest.raises(ValueError, match="重复"):
            validate_profile_bindings(bindings, HorizonConfig().hotkeys)


@pytest.fixture
def api(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows panel")
    from horizon import ipc
    from horizon.console.app import Api

    monkeypatch.setattr(ipc, "find_overlay", lambda: 0)
    return Api(tmp_path / "config.json")


def test_api_bind_rename_copy_delete(api, monkeypatch):
    monkeypatch.setattr(api, "_check_hotkeys", lambda cfg: None)
    original = api.save_profile("探索")[0]
    state = api.bind_profile(original["id"], "Ctrl+Alt+J")
    assert state["config"]["profile_hotkeys"] == {original["id"]: "Ctrl+Alt+J"}
    api.rename_profile(original["id"], "夜间")
    api.duplicate_profile(original["id"])
    assert api.state()["config"]["profile_hotkeys"] == {original["id"]: "Ctrl+Alt+J"}
    api.apply_profile(original["id"])
    assert api.state()["config"]["profile_hotkeys"] == {original["id"]: "Ctrl+Alt+J"}
    api.delete_profile(original["id"])
    assert api.state()["config"]["profile_hotkeys"] == {}
    with pytest.raises(ValueError):
        api.bind_profile(original["id"], "Ctrl+Alt+K")


def test_api_conflicts_and_dialog_cancel(api, monkeypatch):
    monkeypatch.setattr(api, "_check_hotkeys", lambda cfg: None)
    original = api.save_profile("探索")[0]
    with pytest.raises(ValueError, match="重复"):
        api.bind_profile(original["id"], "Ctrl+Alt+H")
    assert api.state()["config"]["profile_hotkeys"] == {}
    api._window = SimpleNamespace(create_file_dialog=lambda *a, **kw: None)
    assert api.import_profile() is None
    assert api.export_profile(original["id"]) is None


def test_api_system_conflict_keeps_previous_binding(api, monkeypatch):
    original = api.save_profile("探索")[0]
    monkeypatch.setattr(api, "_check_hotkeys", lambda cfg: None)
    api.bind_profile(original["id"], "Ctrl+Alt+J")

    def occupied(cfg):
        raise ValueError("占用")

    monkeypatch.setattr(api, "_check_hotkeys", occupied)
    with pytest.raises(ValueError, match="占用"):
        api.bind_profile(original["id"], "Ctrl+Alt+K")
    assert api.state()["config"]["profile_hotkeys"][original["id"]] == "Ctrl+Alt+J"


def test_visual_settings_still_excludes_machine_bindings():
    assert "profile_hotkeys" not in visual_settings(HorizonConfig())


@pytest.fixture
def runtime(store, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows runtime")
    from horizon.overlay import HorizonApp

    app = HorizonApp(HorizonConfig(), store.path.with_name("config.json"))
    app.main = SimpleNamespace(hwnd=11)
    monkeypatch.setattr(app, "redraw", lambda: None)
    monkeypatch.setattr(app, "_sync_hud", lambda: None)
    monkeypatch.setattr(app, "_on_display_change", lambda: None)
    return app


def test_runtime_profile_hotkey_applies_visuals_preserving_machine(runtime, store, monkeypatch):
    from horizon import win32

    identifier = store.list()[0]["id"]
    runtime.cfg.profile_hotkeys = {identifier: "Ctrl+Alt+J"}
    runtime.cfg.monitor = 2
    runtime.cfg.color = "#FFFFFF"
    monkeypatch.setattr(win32, "register_hotkey", lambda *a: True)
    runtime._register_hotkeys()
    key_id = next(k for k, v in runtime.profile_hotkey_map.items() if v == identifier)
    runtime._on_hotkey(key_id)
    assert runtime.cfg.color == "#00FF66"
    assert runtime.cfg.monitor == 2
    assert runtime.cfg.profile_hotkeys == {identifier: "Ctrl+Alt+J"}
    assert load(runtime.cfg_path).color == "#00FF66"


def test_runtime_conflict_rolls_back_and_missing_id_does_nothing(runtime, store, monkeypatch):
    from horizon import ipc, win32

    identifier = store.list()[0]["id"]
    original = runtime.cfg.to_dict()
    monkeypatch.setattr(win32, "register_hotkey", lambda h, i, m, v: v != ord("J"))
    monkeypatch.setattr(
        ipc, "read_payload", lambda _: {"patch": {"profile_hotkeys": {identifier: "Ctrl+J"}}}
    )
    assert runtime._on_copydata(0) == 2
    assert runtime.cfg.to_dict() == original
    monkeypatch.setattr(ipc, "read_payload", lambda _: {"apply_profile": "deleted"})
    assert runtime._on_copydata(0) == 0
    assert runtime.cfg.to_dict() == original


def test_runtime_ipc_applies_by_id_and_tray_matches_current_visuals(runtime, store, monkeypatch):
    from horizon import ipc
    from horizon.tray import custom_profile_items

    identifier = store.list()[0]["id"]
    runtime.cfg.color = "#FFFFFF"
    monkeypatch.setattr(ipc, "read_payload", lambda _: {"apply_profile": identifier})
    assert runtime._on_copydata(0) == 1
    items = list(custom_profile_items(runtime))
    assert items[0].text == "探索"
    assert items[0].checked
    runtime.cfg.color = "#FFFFFF"
    assert not items[0].checked
    store.rename(identifier, "夜间")
    assert list(custom_profile_items(runtime))[0].text == "夜间"
    store.delete(identifier)
    assert not list(custom_profile_items(runtime))[0].enabled


def test_live_reset_clears_bindings_like_offline_reset(runtime, store, monkeypatch):
    from horizon import ipc, win32
    from horizon.console.app import Api

    identifier = store.list()[0]["id"]
    runtime.cfg.profile_hotkeys = {identifier: "Ctrl+Alt+J"}
    monkeypatch.setattr(win32, "register_hotkey", lambda *a: True)
    monkeypatch.setattr(win32, "set_timer", lambda *a: None)
    monkeypatch.setattr(ipc, "find_overlay", lambda: 11)
    monkeypatch.setattr(ipc, "query_state", lambda h: {"config": runtime.cfg.to_dict()})

    def send(hwnd, payload):
        monkeypatch.setattr(ipc, "read_payload", lambda _: payload)
        return runtime._on_copydata(0) == 1

    monkeypatch.setattr(ipc, "send_payload", send)
    result = Api(runtime.cfg_path).reset()
    assert runtime.cfg.profile_hotkeys == result["config"]["profile_hotkeys"] == {}


def test_tray_rebuilds_before_native_right_click():
    if sys.platform != "win32":
        pytest.skip("Windows tray")
    from horizon.tray import make_tray_icon

    events = []

    class NativeIcon:
        def update_menu(self):
            events.append("refresh")

        def _on_notify(self, wparam, lparam):
            events.append(("native", lparam))

    icon = make_tray_icon(SimpleNamespace(Icon=NativeIcon))
    icon._on_notify(0, 0x0205)
    assert events == ["refresh", ("native", 0x0205)]
    events.clear()
    icon._on_notify(0, 0x0202)
    assert events == [("native", 0x0202)]
