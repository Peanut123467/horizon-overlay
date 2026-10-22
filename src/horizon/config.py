"""Configuration model + JSON persistence.

Everything lives in ``%APPDATA%/horizon/config.json``. No network, no telemetry.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .hotkeys import DEFAULT_HOTKEYS, validate_bindings

__all__ = [
    "Vignette",
    "Frame",
    "Reticle",
    "AnchorGrid",
    "Session",
    "Stats",
    "HorizonConfig",
    "default_config",
    "preset",
    "load",
    "save",
    "config_path",
    "next_color",
    "apply_patch",
    "STATS_POSITIONS",
    "PRESETS",
    "COLOR_PALETTE",
]


def config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "horizon" / "config.json"


@dataclass
class Vignette:
    """Radial darkening. The main lever against peripheral optic flow."""

    enabled: bool = True
    inner: float = 0.34  # where the darkening starts
    outer: float = 1.06  # where it reaches full strength
    strength: float = 0.55  # 0..1, max alpha


@dataclass
class Frame:
    """A thin static border that gives the eye a fixed reference edge."""

    enabled: bool = True
    inset: int = 26
    width: int = 8
    alpha: int = 90


@dataclass
class Reticle:
    """A tiny fixed anchor at screen centre (four ticks + a dot)."""

    enabled: bool = True
    size: int = 9
    gap: int = 9
    alpha: int = 150


@dataclass
class AnchorGrid:
    """Very faint static dot grid -- an optional stronger anchor field."""

    enabled: bool = False
    spacing: int = 180
    radius: int = 2
    alpha: int = 16


@dataclass
class Session:
    """Local-only session timer with a gentle on-screen reminder."""

    enabled: bool = True
    minutes: int = 60
    reminder_seconds: int = 3


@dataclass
class Stats:
    """Small HUD with local metrics. Rendered in its own tiny window."""

    enabled: bool = True
    position: str = "top-left"  # top-left | top-right | bottom-left | bottom-right
    font_size: int = 21
    alpha: int = 200
    refresh_ms: int = 1000


@dataclass
class HorizonConfig:
    vignette: Vignette = field(default_factory=Vignette)
    frame: Frame = field(default_factory=Frame)
    reticle: Reticle = field(default_factory=Reticle)
    grid: AnchorGrid = field(default_factory=AnchorGrid)
    session: Session = field(default_factory=Session)
    stats: Stats = field(default_factory=Stats)
    color: str = "#00FF66"  # bright green; applies to frame / reticle / grid / HUD text
    monitor: int = 0
    start_hidden: bool = False
    tray_hint_shown: bool = False  # one-time "where did the icon go" notification
    hotkeys: dict[str, str] = field(default_factory=lambda: DEFAULT_HOTKEYS.copy())

    # -- (de)serialisation -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HorizonConfig:
        cfg = cls()
        for f in fields(cls):
            if f.name not in raw:
                continue
            value = raw[f.name]
            current = getattr(cfg, f.name)
            if hasattr(current, "__dataclass_fields__"):
                if not isinstance(value, dict):
                    continue
                sub = type(current)
                known = {sf.name for sf in fields(sub)}
                setattr(cfg, f.name, sub(**{k: v for k, v in value.items() if k in known}))
            else:
                setattr(cfg, f.name, value)
        return cfg


PRESETS: dict[str, dict[str, Any]] = {
    # Barely noticeable: for people who only want the edge softened.
    "gentle": {
        "vignette": {"enabled": True, "inner": 0.55, "outer": 1.10, "strength": 0.35},
        "frame": {"enabled": True, "inset": 30, "width": 6, "alpha": 70},
        "reticle": {"enabled": False, "size": 9, "gap": 9, "alpha": 150},
        "grid": {"enabled": False, "spacing": 180, "radius": 2, "alpha": 16},
    },
    "standard": {
        "vignette": {"enabled": True, "inner": 0.34, "outer": 1.06, "strength": 0.55},
        "frame": {"enabled": True, "inset": 26, "width": 8, "alpha": 90},
        "reticle": {"enabled": True, "size": 9, "gap": 9, "alpha": 150},
        "grid": {"enabled": False, "spacing": 180, "radius": 2, "alpha": 16},
    },
    # Stronger mask, for short sessions only -- deliberately not the default.
    "strong": {
        "vignette": {"enabled": True, "inner": 0.20, "outer": 0.95, "strength": 0.78},
        "frame": {"enabled": True, "inset": 18, "width": 10, "alpha": 120},
        "reticle": {"enabled": True, "size": 11, "gap": 10, "alpha": 190},
        "grid": {"enabled": True, "spacing": 160, "radius": 2, "alpha": 22},
    },
}

# Cycled by Ctrl+Alt+C. Any "#RRGGBB" value is accepted in the config file;
# this is just a quick way to try a few without editing JSON.
COLOR_PALETTE: tuple[str, ...] = ("#00FF66", "#00E5FF", "#FFFFFF", "#FFD60A", "#B388FF")


def next_color(current: str) -> str:
    """Return the next palette colour, or the first one if ``current`` is custom."""
    normalised = (current or "").strip().upper()
    try:
        idx = [c.upper() for c in COLOR_PALETTE].index(normalised)
    except ValueError:
        return COLOR_PALETTE[0]
    return COLOR_PALETTE[(idx + 1) % len(COLOR_PALETTE)]


def default_config() -> HorizonConfig:
    return HorizonConfig()


def preset(name: str, base: HorizonConfig | None = None) -> HorizonConfig:
    """Return a copy of ``base`` (or defaults) with a named preset applied."""
    cfg = base or default_config()
    data = cfg.to_dict()
    overlay = PRESETS.get(name)
    if overlay is None:
        raise KeyError(f"unknown preset: {name!r} (known: {', '.join(PRESETS)})")
    defaults = default_config().to_dict()
    for section in ("vignette", "frame", "reticle", "grid"):
        data[section] = {**defaults[section], **overlay.get(section, {})}
    return HorizonConfig.from_dict(data)


def load(path: Path | None = None) -> HorizonConfig:
    p = path or config_path()
    if not p.exists():
        return default_config()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_config()
    if not isinstance(raw, dict):
        return default_config()
    return apply_patch(default_config(), raw)


def save(cfg: HorizonConfig, path: Path | None = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return p


# ----------------------------------------------------------------- patching --

# Rendered values must stay inside ranges the compositor can actually handle.
# Out-of-range input is clamped rather than rejected: a slightly wrong slider
# must never be able to produce a config that crashes the renderer.
_LIMITS: dict[tuple[str, str], tuple[float, float]] = {
    ("vignette", "inner"): (0.0, 2.0),
    ("vignette", "outer"): (0.0, 3.0),
    ("vignette", "strength"): (0.0, 1.0),
    ("frame", "inset"): (0, 400),
    ("frame", "width"): (1, 60),
    ("frame", "alpha"): (0, 255),
    ("reticle", "size"): (1, 80),
    ("reticle", "gap"): (0, 80),
    ("reticle", "alpha"): (0, 255),
    ("grid", "spacing"): (24, 2000),
    ("grid", "radius"): (1, 20),
    ("grid", "alpha"): (0, 255),
    ("session", "minutes"): (1, 600),
    ("session", "reminder_seconds"): (3, 120),
    ("stats", "font_size"): (9, 48),
    ("stats", "alpha"): (0, 255),
    ("stats", "refresh_ms"): (250, 10000),
}

STATS_POSITIONS: tuple[str, ...] = ("top-left", "top-right", "bottom-left", "bottom-right")

_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{3}$|^#?[0-9a-fA-F]{6}$")


def _coerce(section: str, name: str, value: Any, default: Any) -> Any:
    """Force ``value`` to the type of ``default``, then clamp it."""
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        try:
            out: float = int(round(float(value)))
        except (TypeError, ValueError, OverflowError):
            return default
    elif isinstance(default, float):
        try:
            out = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
    else:
        return value

    if not math.isfinite(out):
        return default
    limits = _LIMITS.get((section, name))
    if limits:
        low, high = limits
        out = max(low, min(high, out))
    return out


def apply_patch(cfg: HorizonConfig, patch: dict[str, Any]) -> HorizonConfig:
    """Return a new config with ``patch`` merged in, coerced and clamped.

    The console sends partial dicts over IPC, so nothing in here may be
    trusted: unknown keys are dropped, wrong types fall back to the current
    value, numbers are clamped, and an invalid colour keeps the old one.
    """
    if not isinstance(patch, dict):
        return cfg

    merged = cfg.to_dict()
    for key, value in patch.items():
        if key not in merged:
            continue
        if isinstance(value, dict) and isinstance(merged[key], dict):
            for sub_key, sub_value in value.items():
                if sub_key in merged[key]:
                    merged[key][sub_key] = sub_value
        elif not isinstance(merged[key], dict):
            merged[key] = value

    new = HorizonConfig.from_dict(merged)
    try:
        new.hotkeys = validate_bindings(merged["hotkeys"])
    except ValueError:
        new.hotkeys = cfg.hotkeys.copy()

    for section in ("vignette", "frame", "reticle", "grid", "session", "stats"):
        obj = getattr(new, section)
        base = getattr(cfg, section)
        for f in fields(obj):
            setattr(
                obj, f.name, _coerce(section, f.name, getattr(obj, f.name), getattr(base, f.name))
            )

    new.monitor = max(0, _coerce("", "monitor", new.monitor, cfg.monitor))
    new.start_hidden = bool(new.start_hidden)
    new.tray_hint_shown = bool(new.tray_hint_shown)

    colour = str(new.color or "").strip()
    if _HEX_RE.match(colour):
        if not colour.startswith("#"):
            colour = "#" + colour
        if len(colour) == 4:  # #RGB -> #RRGGBB
            colour = "#" + "".join(ch * 2 for ch in colour[1:])
        new.color = colour.upper()
    else:
        new.color = cfg.color

    if new.stats.position not in STATS_POSITIONS:
        new.stats.position = cfg.stats.position

    return new
