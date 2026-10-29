import base64
import io
import json
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

if sys.platform != "win32":
    pytest.skip("Windows panel integration", allow_module_level=True)

from horizon import ipc
from horizon.config import default_config, load
from horizon.console.app import Api


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "find_overlay", lambda: 0)
    return Api(tmp_path / "config.json")


def decode(url):
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def choose(api, path):
    api._window = SimpleNamespace(create_file_dialog=lambda *a, **kw: [str(path)])


def test_profile_roundtrip_and_preserves_nonvisual_settings(api):
    api.patch(
        {
            "color": "#ABCDEF",
            "frame": {"width": 17},
            "monitor": 2,
            "session": {"minutes": 25},
            "stats": {"enabled": False},
        }
    )
    profiles = api.save_profile("我的探索")
    profile = profiles[0]
    assert profile["name"] == "我的探索"
    assert decode(profile["thumbnail"]).width > 0
    api.patch(
        {
            "color": "#FFFFFF",
            "monitor": 1,
            "frame": {"width": 3},
            "session": {"minutes": 40},
            "stats": {"enabled": True},
        }
    )
    state = api.apply_profile(profile["id"])
    assert state["config"]["frame"]["width"] == 17
    assert state["config"]["color"] == "#ABCDEF"
    assert state["config"]["monitor"] == 1
    assert state["config"]["session"]["minutes"] == 40
    assert state["config"]["stats"]["enabled"]
    assert Api(api._cfg_path).profiles()[0]["name"] == "我的探索"


def test_profile_copy_rename_delete_are_persistent(api):
    original = api.save_profile("探索")[0]
    copies = api.duplicate_profile(original["id"])
    assert len(copies) == 2
    duplicate = next(p for p in copies if p["id"] != original["id"])
    assert duplicate["name"] != original["name"]
    renamed = api.rename_profile(duplicate["id"], "  夜间  ")
    assert any(p["name"] == "夜间" for p in renamed)
    assert len(api.delete_profile(original["id"])) == 1
    assert Api(api._cfg_path).profiles()[0]["name"] == "夜间"
    with pytest.raises(ValueError):
        api.apply_profile(original["id"])


@pytest.mark.parametrize("name", ["", "  ", "x" * 41, "bad\nname", None])
def test_invalid_profile_names_do_not_write(api, name):
    with pytest.raises(ValueError):
        api.save_profile(name)
    assert not api._cfg_path.with_name("profiles.json").exists()


def test_duplicate_names_and_corrupt_library_never_overwrite(api):
    api.save_profile("Explore")
    path = api._cfg_path.with_name("profiles.json")
    original = path.read_bytes()
    with pytest.raises(ValueError):
        api.save_profile(" explore ")
    assert path.read_bytes() == original
    path.write_text('{"version":1,"profiles":"broken"}', encoding="utf-8")
    corrupted = path.read_bytes()
    with pytest.raises(ValueError, match="预设"):
        api.save_profile("another")
    assert path.read_bytes() == corrupted


def test_profile_storage_contains_only_visual_data_and_no_screenshot(api, tmp_path):
    screenshot = tmp_path / "private.png"
    Image.new("RGB", (600, 300), "red").save(screenshot)
    choose(api, screenshot)
    api.import_preview()
    api.save_profile("私人方案")
    data = json.loads(api._cfg_path.with_name("profiles.json").read_text(encoding="utf-8"))
    assert set(data["profiles"][0]["visuals"]) == {
        "vignette",
        "frame",
        "triangles",
        "reticle",
        "grid",
        "color",
    }
    assert "private" not in json.dumps(data)
    assert "data:image" not in json.dumps(data)


def test_screenshot_comparison_aspect_and_reset(api, tmp_path):
    path = tmp_path / "wide.png"
    Image.new("RGB", (1600, 400), (210, 100, 45)).save(path)
    choose(api, path)
    result = api.import_preview()
    assert result["name"] == "wide.png"
    raw, effect = decode(result["background"]), decode(api.preview())
    assert raw.size == effect.size
    assert raw.width / raw.height == 4
    assert raw.tobytes() != effect.tobytes()
    assert raw.getpixel((0, 0)) == (210, 100, 45)
    assert not api._cfg_path.exists()
    api.reset_preview()
    assert decode(api.preview_background()).size == decode(api.preview()).size
    assert (
        decode(api.preview_background()).width / decode(api.preview_background()).height == 16 / 9
    )


def test_cancel_invalid_image_and_new_api_keep_privacy(api, tmp_path):
    path = tmp_path / "portrait.png"
    Image.new("RGBA", (200, 400), (255, 0, 0, 100)).save(path)
    choose(api, path)
    api.import_preview()
    original = api.preview_background()
    api._window = SimpleNamespace(create_file_dialog=lambda *a, **kw: None)
    assert api.import_preview() is None
    assert api.preview_background() == original
    path.write_bytes(b"not an image")
    choose(api, path)
    with pytest.raises(ValueError, match="图片"):
        api.import_preview()
    assert api.preview_background() == original
    assert Api(api._cfg_path).preview_background() != original


def test_profile_apply_does_not_change_hotkeys(api):
    profile = api.save_profile("外观")[0]
    initial = default_config().hotkeys
    api.apply_profile(profile["id"])
    assert load(api._cfg_path).hotkeys == initial


@pytest.mark.parametrize(
    "damage", [None, {"width": "broken"}, {"width": 9999}, {"width": True}, "missing"]
)
def test_nested_corruption_is_rejected_without_overwrite(api, damage):
    api.save_profile("保留原始值")
    path = api._cfg_path.with_name("profiles.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    frame = raw["profiles"][0]["visuals"]["frame"]
    if damage is None:
        raw["profiles"][0]["visuals"]["frame"] = None
    elif damage == "missing":
        frame.pop("width")
    else:
        frame.update(damage)
    path.write_text(json.dumps(raw), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="预设"):
        api.rename_profile(raw["profiles"][0]["id"], "新名字")
    assert path.read_bytes() == original
