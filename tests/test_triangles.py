"""Observable geometry, compatibility and persistence of the four edge triangles."""

from __future__ import annotations

import numpy as np
import pytest

from horizon.config import apply_patch, default_config, load, preset, save
from horizon.render import compose, compose_image


def triangles_only(**changes):
    return apply_patch(
        default_config(),
        {
            "vignette": {"enabled": False},
            "frame": {"enabled": False},
            "reticle": {"enabled": False},
            "grid": {"enabled": False},
            "triangles": {"enabled": True, **changes},
        },
    )


def test_triangle_defaults_and_legacy_config(tmp_path):
    expected = {
        "enabled": False,
        "filled": False,
        "base": 50.0,
        "depth": 20.0,
        "width": 3,
        "alpha": 153,
    }
    assert default_config().to_dict().get("triangles") == expected
    old = tmp_path / "legacy.json"
    old.write_text('{"color":"#FFFFFF","frame":{"width":12}}')
    cfg = load(old)
    assert cfg.to_dict()["triangles"] == expected
    assert cfg.frame.width == 12 and cfg.color == "#FFFFFF"


def test_triangle_settings_roundtrip_and_survive_presets(tmp_path):
    cfg = triangles_only(filled=True, base=72, depth=31, width=11, alpha=97)
    path = tmp_path / "config.json"
    save(cfg, path)
    assert load(path).triangles == cfg.triangles
    for name in ("gentle", "standard", "strong"):
        assert preset(name, cfg).triangles == cfg.triangles
    assert not default_config().triangles.enabled


def test_triangle_patch_clamps_and_does_not_mutate():
    cfg = default_config()
    before = cfg.to_dict()
    new = apply_patch(cfg, {"triangles": {"base": 999, "depth": -1, "width": 0, "alpha": 999}})
    assert cfg.to_dict() == before
    assert (new.triangles.base, new.triangles.depth, new.triangles.width, new.triangles.alpha) == (
        100,
        1,
        1,
        255,
    )


@pytest.mark.parametrize("bad", [None, [], "bad", float("nan"), float("inf")])
def test_invalid_dimensions_keep_last_valid_value(bad):
    cfg = triangles_only(base=65, depth=28, width=7, alpha=120)
    new = apply_patch(cfg, {"triangles": dict.fromkeys(("base", "depth", "width", "alpha"), bad)})
    assert new.triangles == cfg.triangles
    assert compose_image(new, 80, 40).getbbox()


@pytest.mark.parametrize("section", [None, [], "broken"])
def test_malformed_triangle_section_is_ignored(section):
    cfg = apply_patch(default_config(), {"triangles": section})
    assert cfg.triangles == default_config().triangles


@pytest.mark.parametrize("filled", [False, True])
def test_all_four_edges_have_inward_tips_and_clear_centre(filled):
    img = compose_image(triangles_only(filled=filled), 401, 201)
    for point in ((200, 40), (200, 160), (80, 100), (320, 100)):
        assert img.getpixel(point)[3] == 153
    assert img.getpixel((200, 100))[3] == 0
    assert img.getpixel((0, 0))[3] == 0


def test_hollow_has_slanted_strokes_but_no_fill_or_base_line():
    img = compose_image(triangles_only(), 401, 201)
    assert img.getpixel((150, 20))[3] == 153
    for point in ((200, 10), (200, 0), (200, 200), (0, 100), (400, 100)):
        assert img.getpixel(point)[3] == 0


def test_solid_fills_the_edge_regions():
    img = compose_image(triangles_only(filled=True), 401, 201)
    for point in ((200, 10), (200, 190), (20, 100), (380, 100)):
        assert img.getpixel(point)[3] == 153


def test_base_and_depth_are_independent():
    normal = compose_image(triangles_only(filled=True), 401, 201)
    narrow = compose_image(triangles_only(filled=True, base=25), 401, 201)
    deep = compose_image(triangles_only(filled=True, depth=40), 401, 201)
    assert normal.getpixel((125, 5))[3] and not narrow.getpixel((125, 5))[3]
    assert normal.getpixel((200, 35)) == narrow.getpixel((200, 35))
    assert not normal.getpixel((200, 60))[3] and deep.getpixel((200, 60))[3]


def test_hollow_line_width_changes_coverage_but_solid_ignores_it():
    thin = compose_image(triangles_only(width=1), 401, 201)
    thick = compose_image(triangles_only(width=9), 401, 201)
    assert np.count_nonzero(np.asarray(thick)[..., 3]) > np.count_nonzero(np.asarray(thin)[..., 3])
    solid1 = compose_image(triangles_only(filled=True, width=1), 401, 201)
    solid9 = compose_image(triangles_only(filled=True, width=9), 401, 201)
    assert solid1.tobytes() == solid9.tobytes()


@pytest.mark.parametrize("filled", [False, True])
def test_triangles_follow_global_colour_opacity_and_premultiplication(filled):
    cfg = triangles_only(filled=filled, alpha=85)
    cfg.color = "#3366FF"
    assert compose_image(cfg, 401, 201).getpixel((200, 40)) == (51, 102, 255, 85)
    arr = np.frombuffer(compose(cfg, 401, 201), dtype=np.uint8).reshape(201, 401, 4)
    assert np.all(arr[..., :3] <= arr[..., 3:4])
    cfg.triangles.alpha = 0
    assert compose_image(cfg, 401, 201).getbbox() is None
    cfg.triangles.alpha = 255
    cfg.triangles.enabled = False
    assert compose_image(cfg, 401, 201).getbbox() is None


@pytest.mark.parametrize("size", [(1, 1), (3, 7), (201, 401), (801, 201), (640, 360)])
def test_screen_shapes_and_overlaps_remain_bounded_at_one_opacity(size):
    cfg = triangles_only(filled=True, base=100, depth=100, alpha=90)
    img = compose_image(cfg, *size)
    assert img.size == size and img.getbbox()
    assert np.asarray(img)[..., 3].max() == 90


def test_triangles_composite_with_existing_effects():
    cfg = triangles_only(filled=True, depth=100)
    cfg.reticle.enabled = True
    assert compose_image(cfg, 401, 201).getpixel((200, 100))[3] > cfg.triangles.alpha
