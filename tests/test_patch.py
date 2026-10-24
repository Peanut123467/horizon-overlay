"""Tests for the IPC patch applier used by the control panel.

The console is a separate process and sends partial dicts, so ``apply_patch``
has to treat every value as untrusted.
"""

from __future__ import annotations

import pytest

from horizon.config import HorizonConfig, apply_patch, default_config


def test_partial_patch_only_touches_named_fields():
    cfg = default_config()
    new = apply_patch(cfg, {"vignette": {"strength": 0.9}})
    assert new.vignette.strength == 0.9
    assert new.vignette.inner == cfg.vignette.inner
    assert new.frame.width == cfg.frame.width


def test_patch_does_not_mutate_the_original():
    cfg = default_config()
    before = cfg.to_dict()
    apply_patch(cfg, {"vignette": {"strength": 0.9}, "color": "#FF0000"})
    assert cfg.to_dict() == before


def test_unknown_keys_are_dropped():
    cfg = default_config()
    new = apply_patch(cfg, {"nonsense": 1, "vignette": {"zzz": 2}})
    assert new.to_dict() == cfg.to_dict()


def test_numeric_values_are_clamped():
    new = apply_patch(default_config(), {"frame": {"width": 9999, "alpha": -50}})
    assert new.frame.width == 60
    assert new.frame.alpha == 0


def test_string_numbers_are_coerced():
    new = apply_patch(default_config(), {"frame": {"width": "12"}})
    assert new.frame.width == 12
    assert isinstance(new.frame.width, int)


def test_garbage_numbers_fall_back_to_current():
    cfg = default_config()
    new = apply_patch(cfg, {"vignette": {"strength": "abc"}})
    assert new.vignette.strength == cfg.vignette.strength


def test_booleans_are_coerced():
    new = apply_patch(default_config(), {"frame": {"enabled": 0}, "stats": {"enabled": 1}})
    assert new.frame.enabled is False
    assert new.stats.enabled is True


@pytest.mark.parametrize(
    "given,expected",
    [
        ("#ff0000", "#FF0000"),
        ("ff0000", "#FF0000"),
        ("#f00", "#FF0000"),
        ("0f0", "#00FF00"),
    ],
)
def test_colour_is_normalised(given, expected):
    assert apply_patch(default_config(), {"color": given}).color == expected


def test_invalid_colour_keeps_the_old_one():
    cfg = default_config()
    assert apply_patch(cfg, {"color": "not-a-colour"}).color == cfg.color
    assert apply_patch(cfg, {"color": ""}).color == cfg.color
    assert apply_patch(cfg, {"color": None}).color == cfg.color


def test_invalid_stats_position_keeps_the_old_one():
    cfg = default_config()
    new = apply_patch(cfg, {"stats": {"position": "middle"}})
    assert new.stats.position == cfg.stats.position


def test_valid_stats_position_is_accepted():
    new = apply_patch(default_config(), {"stats": {"position": "bottom-right"}})
    assert new.stats.position == "bottom-right"


def test_non_dict_patch_is_ignored():
    cfg = default_config()
    assert apply_patch(cfg, None) is cfg
    assert apply_patch(cfg, ["nope"]) is cfg


def test_full_dict_patch_roundtrips():
    cfg = default_config()
    payload = cfg.to_dict()
    payload["vignette"]["strength"] = 0.42
    assert apply_patch(cfg, payload).to_dict()["vignette"]["strength"] == 0.42


def test_patch_preserves_tray_hint_flag():
    cfg = default_config()
    cfg.tray_hint_shown = True
    assert apply_patch(cfg, {"color": "#FFFFFF"}).tray_hint_shown is True


def test_result_is_a_new_object():
    cfg = default_config()
    assert apply_patch(cfg, {"color": "#FFFFFF"}) is not cfg
    assert isinstance(apply_patch(cfg, {}), HorizonConfig)


@pytest.mark.parametrize("value", ["false", "False", "  OFF  ", "0", "no"])
def test_false_strings_disable_boolean_fields(value):
    cfg = default_config()
    cfg.start_hidden = True
    new = apply_patch(cfg, {"frame": {"enabled": value}, "start_hidden": value})
    assert new.frame.enabled is False
    assert new.start_hidden is False


@pytest.mark.parametrize("value", ["true", "YES", "1", " on "])
def test_true_strings_enable_boolean_fields(value):
    new = apply_patch(default_config(), {"grid": {"enabled": value}})
    assert new.grid.enabled is True


@pytest.mark.parametrize("value", ["maybe", "", [], {}, None, 2])
def test_invalid_booleans_keep_current_value(value):
    cfg = default_config()
    new = apply_patch(cfg, {"grid": {"enabled": value}, "frame": {"enabled": value}})
    assert new.grid.enabled is False
    assert new.frame.enabled is True


@pytest.mark.parametrize("inner,outer", [(1.5, 0.5), (0.8, 0.5), (0.5, 0.5), (0.51, 0.5)])
def test_vignette_radii_always_have_a_smooth_transition(inner, outer):
    cfg = apply_patch(default_config(), {"vignette": {"inner": inner, "outer": outer}})
    assert cfg.vignette.inner < cfg.vignette.outer
    assert cfg.vignette.outer - cfg.vignette.inner >= 0.05 - 1e-9
