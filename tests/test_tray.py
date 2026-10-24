"""Tests for the tray menu's settings plumbing.

Everything here is pure logic -- no window is created and no icon is shown.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows tray integration", allow_module_level=True)

from horizon.config import COLOR_PALETTE, PRESETS, default_config, preset
from horizon.overlay import (
    PRESET_NAMES,
    SET_COLOR,
    SET_FRAME,
    SET_GRID,
    SET_PRESET,
    SET_RETICLE,
    SET_STATS,
    SET_VIGNETTE,
    VIGNETTE_LEVELS,
    apply_setting,
)
from horizon.tray import COLOR_NAMES, _preset_key, _vignette_level, make_icon_image


def test_every_palette_colour_has_a_label():
    for hex_value in COLOR_PALETTE:
        assert hex_value.upper() in COLOR_NAMES


def test_set_color_maps_index_to_palette():
    cfg = default_config()
    result = apply_setting(cfg, SET_COLOR, 1)
    assert result is cfg
    assert cfg.color == COLOR_PALETTE[1]


def test_set_color_wraps_out_of_range_index():
    cfg = default_config()
    apply_setting(cfg, SET_COLOR, len(COLOR_PALETTE) + 2)
    assert cfg.color == COLOR_PALETTE[2]


def test_set_preset_returns_a_new_config():
    cfg = default_config()
    before = cfg.to_dict()
    result = apply_setting(cfg, SET_PRESET, PRESET_NAMES.index("strong"))
    assert result is not cfg, "preset must not mutate the caller's object in place"
    assert result.vignette.strength > before["vignette"]["strength"]
    assert cfg.to_dict() == before, "original config must be untouched"


def test_set_preset_rejects_out_of_range():
    assert apply_setting(default_config(), SET_PRESET, 99) is None


def test_set_vignette_levels():
    cfg = default_config()
    apply_setting(cfg, SET_VIGNETTE, 0)
    assert cfg.vignette.enabled is False
    apply_setting(cfg, SET_VIGNETTE, 3)
    assert cfg.vignette.enabled is True
    assert cfg.vignette.strength == VIGNETTE_LEVELS[3]


def test_set_vignette_clamps_out_of_range():
    cfg = default_config()
    apply_setting(cfg, SET_VIGNETTE, 99)
    assert cfg.vignette.strength == VIGNETTE_LEVELS[-1]


@pytest.mark.parametrize(
    "action,attr",
    [(SET_FRAME, "frame"), (SET_RETICLE, "reticle"), (SET_GRID, "grid"), (SET_STATS, "stats")],
)
def test_toggles_set_explicit_value(action, attr):
    cfg = default_config()
    apply_setting(cfg, action, 0)
    assert getattr(cfg, attr).enabled is False
    apply_setting(cfg, action, 1)
    assert getattr(cfg, attr).enabled is True


def test_unknown_action_returns_none():
    assert apply_setting(default_config(), 999, 0) is None


def test_triangles_tray_toggle_preserves_shape_settings():
    from horizon import overlay

    cfg = default_config()
    cfg.triangles.filled = True
    cfg.triangles.width = 8
    cfg.triangles.alpha = 101
    assert apply_setting(cfg, overlay.SET_TRIANGLES, 1) is cfg
    assert cfg.triangles.enabled
    apply_setting(cfg, overlay.SET_TRIANGLES, 0)
    assert not cfg.triangles.enabled
    assert cfg.triangles.filled and cfg.triangles.width == 8 and cfg.triangles.alpha == 101
    assert _preset_key(type("A", (), {"cfg": cfg})()) == "standard"


def test_preset_key_detects_default():
    cfg = default_config()
    assert _preset_key(type("A", (), {"cfg": cfg})()) == "standard"


def test_preset_key_detects_each_named_preset():
    for name in PRESETS:
        cfg = preset(name)
        fake = type("A", (), {"cfg": cfg})()
        assert _preset_key(fake) == name


def test_preset_key_ignores_colour_and_stats():
    cfg = preset("gentle")
    cfg.color = "#FFD60A"
    cfg.stats.enabled = False
    fake = type("A", (), {"cfg": cfg})()
    assert _preset_key(fake) == "gentle"


def test_preset_key_returns_none_when_hand_tuned():
    cfg = default_config()
    cfg.vignette.strength = 0.5
    fake = type("A", (), {"cfg": cfg})()
    assert _preset_key(fake) is None


def test_vignette_level_reflects_enabled_flag():
    cfg = default_config()
    cfg.vignette.strength = 0.55
    fake = type("A", (), {"cfg": cfg})()
    assert _vignette_level(fake) == 0.55
    cfg.vignette.enabled = False
    assert _vignette_level(fake) == 0.0


def test_icon_image_is_rgba_and_not_empty():
    img = make_icon_image("#00FF66")
    assert img.size == (64, 64)
    assert img.mode == "RGBA"
    assert img.getbbox() is not None, "icon must not be fully transparent"


def test_icon_image_follows_colour():
    green = make_icon_image("#00FF66").getpixel((32, 32))
    purple = make_icon_image("#B388FF").getpixel((32, 32))
    assert green != purple
