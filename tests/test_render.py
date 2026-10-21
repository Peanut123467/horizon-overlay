"""Tests for the render pipeline and config model.

These run headless -- no window is created, so they work in CI on any OS.
"""

from __future__ import annotations

import numpy as np
import pytest

from horizon.config import (
    COLOR_PALETTE,
    AnchorGrid,
    Frame,
    HorizonConfig,
    Reticle,
    Vignette,
    default_config,
    load,
    next_color,
    preset,
    save,
)
from horizon.render import DEFAULT_COLOR, compose, compose_image, compose_stats, parse_color


def _vignette_only(**kwargs) -> HorizonConfig:
    return HorizonConfig(
        vignette=Vignette(**kwargs),
        frame=Frame(enabled=False),
        reticle=Reticle(enabled=False),
        grid=AnchorGrid(enabled=False),
    )


@pytest.mark.parametrize("size", [(64, 48), (320, 180), (1280, 720), (2560, 1440)])
def test_compose_returns_exact_buffer_size(size):
    w, h = size
    data = compose(default_config(), w, h)
    assert len(data) == w * h * 4


def test_compose_rejects_bad_size():
    with pytest.raises(ValueError):
        compose(default_config(), 0, 100)


def test_vignette_clears_centre_and_masks_corners():
    cfg = _vignette_only(enabled=True, inner=0.34, outer=1.06, strength=0.55)
    w, h = 320, 180
    arr = np.frombuffer(compose(cfg, w, h), dtype=np.uint8).reshape(h, w, 4)

    assert arr[h // 2, w // 2, 3] == 0, "centre must stay fully transparent"
    assert arr[0, 0, 3] > 40, "corner must be masked"
    assert arr[0, 0, 3] < 255, "corner must not be fully opaque"


def test_vignette_alpha_is_monotonic_toward_corners():
    cfg = _vignette_only(enabled=True, inner=0.3, outer=1.0, strength=0.6)
    w, h = 200, 200
    arr = np.frombuffer(compose(cfg, w, h), dtype=np.uint8).reshape(h, w, 4)
    centre = arr[h // 2, w // 2, 3]
    mid = arr[h // 2, int(w * 0.12), 3]
    corner = arr[0, 0, 3]
    assert centre <= mid <= corner


def test_disabled_vignette_is_fully_transparent():
    cfg = _vignette_only(enabled=False)
    data = compose(cfg, 64, 48)
    assert set(data) == {0}


def test_reticle_paints_the_centre():
    cfg = HorizonConfig(
        vignette=Vignette(enabled=False),
        frame=Frame(enabled=False),
        reticle=Reticle(enabled=True, size=7, gap=8, alpha=120),
        grid=AnchorGrid(enabled=False),
    )
    w, h = 320, 180
    arr = np.frombuffer(compose(cfg, w, h), dtype=np.uint8).reshape(h, w, 4)
    assert arr[h // 2, w // 2, 3] > 0


def test_premultiplied_alpha_invariant():
    """For premultiplied BGRA every colour channel must be <= alpha."""
    cfg = default_config()
    arr = np.frombuffer(compose(cfg, 160, 120), dtype=np.uint8).reshape(120, 160, 4)
    bgr = arr[..., :3].astype(np.int16)
    alpha = arr[..., 3].astype(np.int16)[..., None]
    assert np.all(bgr <= alpha), "colour channel exceeds alpha -> not premultiplied"


def test_compose_image_matches_compose_bytes():
    cfg = default_config()
    img = compose_image(cfg, 96, 64)
    assert img.size == (96, 64)
    assert img.mode == "RGBA"
    assert len(compose(cfg, 96, 64)) == 96 * 64 * 4


def test_config_roundtrip(tmp_path):
    cfg = preset("strong")
    path = tmp_path / "config.json"
    save(cfg, path)
    loaded = load(path)
    assert loaded.to_dict() == cfg.to_dict()


def test_load_missing_file_returns_defaults(tmp_path):
    cfg = load(tmp_path / "nope.json")
    assert cfg.to_dict() == default_config().to_dict()


def test_load_corrupt_file_returns_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert load(path).to_dict() == default_config().to_dict()


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"monitor": 2, "nonsense": 1, "vignette": {"strength": 0.2, "zzz": 9}}', encoding="utf-8"
    )
    cfg = load(path)
    assert cfg.monitor == 2
    assert cfg.vignette.strength == 0.2


def test_preset_strength_increases_masking():
    base = default_config()
    strong = preset("strong", base)
    gentle = preset("gentle", base)
    assert strong.vignette.strength > base.vignette.strength > gentle.vignette.strength
    assert strong.vignette.inner < base.vignette.inner < gentle.vignette.inner


def test_preset_unknown_raises():
    with pytest.raises(KeyError):
        preset("does-not-exist")


def test_preset_does_not_mutate_base():
    base = default_config()
    before = base.to_dict()
    preset("strong", base)
    assert base.to_dict() == before


# --------------------------------------------------------------------- colour


@pytest.mark.parametrize(
    "value,expected",
    [
        ("#00FF66", (0, 255, 102)),
        ("00ff66", (0, 255, 102)),
        ("0F6", (0, 255, 102)),
        ("  #FF0000  ", (255, 0, 0)),
        ("", DEFAULT_COLOR),
        ("nonsense", DEFAULT_COLOR),
        ("#GGGGGG", DEFAULT_COLOR),
        ("#12345", DEFAULT_COLOR),
    ],
)
def test_parse_color(value, expected):
    assert parse_color(value) == expected


def test_default_colour_is_bright_green():
    assert default_config().color.upper() == "#00FF66"


def test_frame_uses_configured_colour():
    cfg = HorizonConfig(
        vignette=Vignette(enabled=False),
        frame=Frame(enabled=True, inset=10, width=4, alpha=255),
        reticle=Reticle(enabled=False),
        grid=AnchorGrid(enabled=False),
        color="#FF0000",
    )
    w = h = 100
    arr = np.frombuffer(compose(cfg, w, h), dtype=np.uint8).reshape(h, w, 4)
    # BGRA: a red frame must show up as B=0, G=0, R=255
    b, g, r, a = arr[h // 2, 11]
    assert (int(r), int(g), int(b), int(a)) == (255, 0, 0, 255)


def test_thicker_border_covers_more_pixels():
    def masked_pixels(width: int) -> int:
        cfg = HorizonConfig(
            vignette=Vignette(enabled=False),
            frame=Frame(enabled=True, inset=10, width=width, alpha=255),
            reticle=Reticle(enabled=False),
            grid=AnchorGrid(enabled=False),
            color="#FFFFFF",
        )
        arr = np.frombuffer(compose(cfg, 100, 100), dtype=np.uint8).reshape(100, 100, 4)
        return int(np.count_nonzero(arr[..., 3]))

    assert masked_pixels(6) > masked_pixels(2)


def test_next_color_cycles_through_palette():
    seen = [COLOR_PALETTE[0]]
    for _ in range(len(COLOR_PALETTE) - 1):
        seen.append(next_color(seen[-1]))
    assert seen == list(COLOR_PALETTE)
    assert next_color(seen[-1]) == COLOR_PALETTE[0]


def test_next_color_from_custom_value_returns_first():
    assert next_color("#123456") == COLOR_PALETTE[0]


# ------------------------------------------------------------------------ hud


def test_compose_stats_buffer_matches_reported_size():
    cfg = default_config()
    bgra, w, h = compose_stats(cfg, "275Hz  ·  内存 71MB  ·  系统 60%")
    assert len(bgra) == w * h * 4
    assert w > 80 and h > 12


def test_compose_stats_is_premultiplied():
    bgra, w, h = compose_stats(default_config(), "144Hz")
    arr = np.frombuffer(bgra, dtype=np.uint8).reshape(h, w, 4)
    bgr = arr[..., :3].astype(np.int16)
    alpha = arr[..., 3].astype(np.int16)[..., None]
    assert np.all(bgr <= alpha)


def test_stats_image_size_grows_with_text():
    cfg = default_config()
    _, w_short, _ = compose_stats(cfg, "1Hz")
    _, w_long, _ = compose_stats(cfg, "275Hz  ·  内存 999MB  ·  系统 99%  ·  重绘 999ms")
    assert w_long > w_short


def test_stats_font_size_affects_height():
    small = default_config()
    small.stats.font_size = 10
    large = default_config()
    large.stats.font_size = 24
    _, _, h_small = compose_stats(small, "144Hz")
    _, _, h_large = compose_stats(large, "144Hz")
    assert h_large > h_small


def test_stats_config_roundtrip(tmp_path):
    cfg = default_config()
    cfg.stats.enabled = False
    cfg.stats.position = "bottom-right"
    cfg.stats.font_size = 18
    path = tmp_path / "config.json"
    save(cfg, path)
    loaded = load(path)
    assert loaded.stats.enabled is False
    assert loaded.stats.position == "bottom-right"
    assert loaded.stats.font_size == 18
