"""Compose the overlay into premultiplied BGRA bytes.

The output is exactly what ``UpdateLayeredWindow`` wants (``AC_SRC_ALPHA``), so
the whole pipeline is: numpy -> Pillow -> premultiply -> raw bytes.

Everything is cached: a full-screen recomposition costs tens of milliseconds, so
we only do it when a parameter actually changes -- never per frame.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import HorizonConfig, normalize_vignette_radii

__all__ = [
    "compose",
    "compose_image",
    "compose_stats",
    "save_preview",
    "save_comparison",
    "parse_color",
]

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhl.ttc",
    r"C:\Windows\Fonts\segoeui.ttf",
)

DEFAULT_COLOR = (0, 255, 102)  # bright green


def parse_color(value: str) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` / ``#RGB``. Falls back to the default green."""
    if not value:
        return DEFAULT_COLOR
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return DEFAULT_COLOR
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return DEFAULT_COLOR


@lru_cache(maxsize=1)
def _vignette_alpha(
    width: int, height: int, inner: float, outer: float, strength: float
) -> np.ndarray:
    """Radial alpha ramp, 0 at centre -> ``strength`` at the corners."""
    inner, outer = normalize_vignette_radii(inner, outer)
    ys = np.linspace(-1.0, 1.0, height, dtype=np.float32)[:, None]
    xs = np.linspace(-1.0, 1.0, width, dtype=np.float32)[None, :]
    dist = np.sqrt(xs * xs + ys * ys) / np.float32(np.sqrt(2.0))

    span = max(outer - inner, 1e-3)
    t = np.clip((dist - inner) / span, 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)  # smoothstep: no visible banding edge
    return (t * float(strength) * 255.0).astype(np.uint8)


@lru_cache(maxsize=4)
def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _draw_frame(draw: ImageDraw.ImageDraw, w: int, h: int, cfg: HorizonConfig, rgb) -> None:
    f = cfg.frame
    inset = max(0, min(f.inset, (min(w, h) - 1) // 2))
    draw.rectangle(
        (inset, inset, w - 1 - inset, h - 1 - inset),
        outline=(*rgb, max(0, min(255, f.alpha))),
        width=max(1, f.width),
    )


def _draw_reticle(draw: ImageDraw.ImageDraw, w: int, h: int, cfg: HorizonConfig, rgb) -> None:
    r = cfg.reticle
    cx, cy = w // 2, h // 2
    alpha = max(0, min(255, r.alpha))
    gap, size = max(1, r.gap), max(1, r.size)
    colour = (*rgb, alpha)
    draw.line((cx - gap - size, cy, cx - gap, cy), fill=colour, width=1)
    draw.line((cx + gap, cy, cx + gap + size, cy), fill=colour, width=1)
    draw.line((cx, cy - gap - size, cx, cy - gap), fill=colour, width=1)
    draw.line((cx, cy + gap, cx, cy + gap + size), fill=colour, width=1)
    draw.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=colour)


def _draw_triangles(draw: ImageDraw.ImageDraw, w: int, h: int, cfg: HorizonConfig, rgb) -> None:
    t = cfg.triangles
    right, bottom = w - 1, h - 1
    cx, cy = right / 2, bottom / 2
    half_x = right * max(1.0, min(100.0, t.base)) / 200
    half_y = bottom * max(1.0, min(100.0, t.base)) / 200
    dx = right * max(1.0, min(100.0, t.depth)) / 100
    dy = bottom * max(1.0, min(100.0, t.depth)) / 100
    colour = (*rgb, max(0, min(255, t.alpha)))
    paths = (
        ((cx - half_x, 0), (cx, dy), (cx + half_x, 0)),
        ((cx - half_x, bottom), (cx, bottom - dy), (cx + half_x, bottom)),
        ((0, cy - half_y), (dx, cy), (0, cy + half_y)),
        ((right, cy - half_y), (right - dx, cy), (right, cy + half_y)),
    )
    for points in paths:
        if t.filled:
            draw.polygon(points, fill=colour)
        else:
            # Deliberately open: the screen edge supplies the triangle's base.
            draw.line(points, fill=colour, width=max(1, t.width), joint="curve")


def _draw_grid(draw: ImageDraw.ImageDraw, w: int, h: int, cfg: HorizonConfig, rgb) -> None:
    g = cfg.grid
    spacing = max(24, g.spacing)
    radius = max(1, g.radius)
    colour = (*rgb, max(0, min(255, g.alpha)))
    for y in range(spacing // 2, h, spacing):
        for x in range(spacing // 2, w, spacing):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=colour)


def _draw_notice(draw: ImageDraw.ImageDraw, w: int, h: int, text: str) -> None:
    font = _load_font(max(13, min(22, h // 48)))
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        tw, th = right - left, bottom - top
    except (AttributeError, ValueError):
        tw, th = len(text) * 9, 16
    x = (w - tw) // 2
    y = h - th - max(40, h // 14)
    pad = 12
    draw.rounded_rectangle(
        (x - pad, y - pad, x + tw + pad, y + th + pad),
        radius=8,
        fill=(18, 18, 22, 170),
    )
    draw.text((x, y), text, font=font, fill=(240, 240, 245, 230))


def compose_image(
    cfg: HorizonConfig, width: int, height: int, notice: str | None = None
) -> Image.Image:
    """Render the overlay as a straight-alpha RGBA image."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    base = np.zeros((height, width, 4), dtype=np.uint8)

    v = cfg.vignette
    if v.enabled and v.strength > 0:
        base[..., 3] = _vignette_alpha(
            width, height, float(v.inner), float(v.outer), float(v.strength)
        )

    canvas = Image.fromarray(base)
    rgb = parse_color(cfg.color)
    if cfg.triangles.enabled and cfg.triangles.alpha > 0:
        triangles = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        _draw_triangles(ImageDraw.Draw(triangles), width, height, cfg, rgb)
        canvas = Image.alpha_composite(canvas, triangles)

    shapes = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shapes)
    if cfg.grid.enabled:
        _draw_grid(draw, width, height, cfg, rgb)
    if cfg.frame.enabled:
        _draw_frame(draw, width, height, cfg, rgb)
    if cfg.reticle.enabled:
        _draw_reticle(draw, width, height, cfg, rgb)
    if notice:
        _draw_notice(draw, width, height, notice)

    return Image.alpha_composite(canvas, shapes)


def compose(cfg: HorizonConfig, width: int, height: int, notice: str | None = None) -> bytes:
    """Render the overlay and return premultiplied BGRA bytes for Win32."""
    return _to_premultiplied_bgra(compose_image(cfg, width, height, notice))


def _to_premultiplied_bgra(img: Image.Image) -> bytes:
    arr = np.asarray(img, dtype=np.uint16)
    alpha = arr[..., 3:4]
    rgb = (arr[..., :3] * alpha + 127) // 255  # premultiply, rounded
    out = np.empty_like(arr)
    out[..., :3] = rgb
    out[..., 3] = arr[..., 3]
    return Image.fromarray(out.astype(np.uint8)).tobytes("raw", "BGRA")


# --------------------------------------------------------------------- hud --


def stats_image(cfg: HorizonConfig, text: str) -> Image.Image:
    """Render the stats HUD as a straight-alpha RGBA image."""
    st = cfg.stats
    font = _load_font(max(9, st.font_size))
    rgb = parse_color(cfg.color)

    probe = Image.new("RGBA", (1, 1))
    left, top, right, bottom = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
    text_w, text_h = max(1, right - left), max(1, bottom - top)

    pad_x, pad_y = 12, 7
    w = text_w + pad_x * 2
    h = text_h + pad_y * 2

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, w - 1, h - 1), radius=7, fill=(0, 0, 0, max(0, min(255, st.alpha)))
    )
    draw.text((pad_x - left, pad_y - top), text, font=font, fill=(*rgb, 255))
    return img


def compose_stats(cfg: HorizonConfig, text: str) -> tuple[bytes, int, int]:
    """Render the stats HUD into its own tiny buffer.

    Returned as ``(premultiplied_bgra, width, height)``. Kept separate from the
    main overlay on purpose: the HUD refreshes about once a second, and a
    full-screen recomposition costs ~60 ms at 1080p / ~108 ms at 1440p. A
    ~300x30 buffer is three orders of magnitude cheaper.
    """
    img = stats_image(cfg, text)
    return _to_premultiplied_bgra(img), img.width, img.height


def _paste_hud(canvas: Image.Image, cfg: HorizonConfig, text: str, origin_x: int = 0) -> None:
    hud = stats_image(cfg, text)
    margin = max(6, cfg.frame.inset) + 14
    pos = cfg.stats.position or "top-left"
    x = origin_x + (margin if "left" in pos else canvas.width - margin - hud.width)
    y = margin if "top" in pos else canvas.height - margin - hud.height
    canvas.alpha_composite(hud, (max(0, x), max(0, y)))


# ------------------------------------------------------------------ preview --


def _fake_scene(width: int, height: int) -> Image.Image:
    """A synthetic 'game frame' so the overlay is visible in a still preview.

    Deliberately mid-tone and fairly flat -- a strongly graded background hides
    the vignette shape we are trying to show.
    """
    horizon = int(height * 0.50)
    sky = np.empty((horizon, width, 3), dtype=np.uint8)
    ground = np.empty((height - horizon, width, 3), dtype=np.uint8)

    t = np.linspace(0.0, 1.0, horizon, dtype=np.float32)[:, None]
    sky[..., 0] = (150 - 30 * t).astype(np.uint8)
    sky[..., 1] = (162 - 32 * t).astype(np.uint8)
    sky[..., 2] = (178 - 34 * t).astype(np.uint8)

    g = np.linspace(0.0, 1.0, height - horizon, dtype=np.float32)[:, None]
    ground[..., 0] = (96 - 34 * g).astype(np.uint8)
    ground[..., 1] = (100 - 36 * g).astype(np.uint8)
    ground[..., 2] = (108 - 38 * g).astype(np.uint8)

    rgb = np.vstack([sky, ground])
    scene = Image.fromarray(rgb).convert("RGBA")

    draw = ImageDraw.Draw(scene, "RGBA")
    for i in range(-7, 8):
        x0 = width // 2 + i * (width // 13)
        draw.line((width // 2, horizon, x0, height), fill=(220, 226, 235, 70), width=2)
    draw.rectangle((0, horizon - 1, width, horizon + 1), fill=(226, 232, 240, 110))
    return scene


def mock_frame(cfg: HorizonConfig, width: int = 480, height: int = 270) -> Image.Image:
    """The overlay composited over a synthetic scene.

    Used by the control panel preview: the real game frame is never captured,
    so the preview is honest about being a mock, but it does go through the
    exact same compositor the overlay uses.
    """
    return Image.alpha_composite(
        _fake_scene(width, height), compose_image(cfg, width, height)
    ).convert("RGB")


def save_preview(
    cfg: HorizonConfig,
    path: str | Path,
    width: int = 1920,
    height: int = 1080,
    notice: str | None = None,
    hud_text: str | None = None,
) -> Path:
    """Write a PNG of the overlay over a synthetic background (for docs/demo)."""
    scene = _fake_scene(width, height)
    overlay = compose_image(cfg, width, height, notice)
    if hud_text and cfg.stats.enabled:
        _paste_hud(overlay, cfg, hud_text)
    out = Image.alpha_composite(scene, overlay).convert("RGB")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    out.save(p)
    return p


def save_comparison(
    cfg: HorizonConfig,
    path: str | Path,
    width: int = 1600,
    height: int = 900,
    hud_text: str | None = None,
) -> Path:
    """Write a side-by-side PNG: overlay off (left) vs on (right)."""
    scene = _fake_scene(width, height)
    left = scene.convert("RGB")

    right_img = compose_image(cfg, width, height)
    if hud_text and cfg.stats.enabled:
        _paste_hud(right_img, cfg, hud_text)
    right = Image.alpha_composite(scene, right_img).convert("RGB")

    gap = 16
    canvas = Image.new("RGB", (width * 2 + gap, height), (14, 14, 16))
    canvas.paste(left, (0, 0))
    canvas.paste(right, (width + gap, 0))

    draw = ImageDraw.Draw(canvas)
    font = _load_font(max(14, height // 40))
    for x, label in ((0, "关闭"), (width + gap, "开启")):
        draw.rectangle((x + 16, height - 50, x + 16 + 92, height - 16), fill=(0, 0, 0, 170))
        draw.text((x + 30, height - 44), label, font=font, fill=(240, 240, 245))

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(p)
    return p
