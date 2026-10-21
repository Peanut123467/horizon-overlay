"""Command line entry point: ``python -m horizon``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .config import PRESETS, config_path, load, preset, save

# Launched from the packaged exe (or `horizonw`) there is no console at all:
# sys.stdout/sys.stderr are None and a bare print() would raise. Remember that
# fact before we swap in a sink, so logging can still go to a file.
_HAS_CONSOLE = sys.stdout is not None
if not _HAS_CONSOLE:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT, e.g. 1920x1080") from exc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="horizon",
        description="A click-through overlay that softens the edges of a 3D game. "
        "It does not touch the game process or its files.",
    )
    p.add_argument("--version", action="version", version=f"horizon {__version__}")
    p.add_argument("--config", type=Path, default=None, help="config file path")
    p.add_argument("--monitor", type=int, default=None, help="monitor index (0 = primary)")
    p.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default=None,
        help="start with a named preset (overrides the saved config for this run)",
    )
    p.add_argument(
        "--preview",
        type=Path,
        default=None,
        metavar="PNG",
        help="render a preview PNG over a synthetic background and exit",
    )
    p.add_argument(
        "--size",
        type=_parse_size,
        default=(1920, 1080),
        help="preview size, default 1920x1080",
    )
    p.add_argument(
        "--compare",
        action="store_true",
        help="with --preview: render a side-by-side 'off vs on' image",
    )
    p.add_argument(
        "--color",
        default=None,
        metavar="#RRGGBB",
        help="override the accent colour for this run (default #00FF66)",
    )
    p.add_argument("--no-stats", action="store_true", help="disable the stats HUD")
    p.add_argument(
        "--duration",
        type=float,
        default=None,
        help="auto-quit after N seconds (useful for smoke tests)",
    )
    p.add_argument("--no-tray", action="store_true", help="do not create a tray icon")
    p.add_argument("--print-config", action="store_true", help="print effective config and exit")
    p.add_argument("--self-test", action="store_true", help="run an internal render check and exit")
    return p


def _resolve_config(args) -> tuple:
    path = args.config or config_path()
    cfg = load(path)
    if args.preset:
        cfg = preset(args.preset, cfg)
    if args.monitor is not None:
        cfg.monitor = args.monitor
    if args.color:
        cfg.color = args.color
    if args.no_stats:
        cfg.stats.enabled = False
    return cfg, path


def _self_test() -> int:
    from .config import AnchorGrid, Frame, HorizonConfig, Reticle, Vignette, default_config
    from .render import compose

    # 1) vignette alone: centre stays clear, corners get masked
    only_vignette = HorizonConfig(
        vignette=Vignette(enabled=True, inner=0.34, outer=1.06, strength=0.55),
        frame=Frame(enabled=False),
        reticle=Reticle(enabled=False),
        grid=AnchorGrid(enabled=False),
    )
    for w, h in [(320, 180), (1280, 720), (1920, 1080), (3440, 1440)]:
        data = compose(only_vignette, w, h)
        assert len(data) == w * h * 4, f"{w}x{h}: wrong buffer size"
        centre_alpha = data[((h // 2) * w + (w // 2)) * 4 + 3]
        corner_alpha = data[0 * w + 0 * 4 + 3]
        assert centre_alpha < 4, f"{w}x{h}: centre not clear (alpha={centre_alpha})"
        assert corner_alpha > 40, f"{w}x{h}: corner not masked (alpha={corner_alpha})"
        print(
            f"  {w}x{h}: {len(data):,} bytes  "
            f"centre_alpha={centre_alpha} corner_alpha={corner_alpha}"
        )

    # 2) reticle actually paints the centre pixel
    with_reticle = HorizonConfig(
        vignette=Vignette(enabled=False),
        reticle=Reticle(enabled=True, size=7, gap=8, alpha=120),
    )
    w, h = 320, 180
    data = compose(with_reticle, w, h)
    centre_alpha = data[((h // 2) * w + (w // 2)) * 4 + 3]
    assert centre_alpha > 0, "reticle did not paint the centre pixel"
    print(f"  reticle: centre_alpha={centre_alpha}")

    # 3) accent colour reaches the pixels (BGRA order, premultiplied)
    from .render import compose_stats, parse_color

    assert parse_color("#00FF66") == (0, 255, 102)
    assert parse_color("0f6") == (0, 255, 102)
    assert parse_color("nonsense") == (0, 255, 102), "bad colour must fall back"

    hud_bytes, hud_w, hud_h = compose_stats(default_config(), "144Hz · 内存 38MB")
    assert len(hud_bytes) == hud_w * hud_h * 4, "stats buffer size mismatch"
    print(f"  stats hud: {hud_w}x{hud_h} ({len(hud_bytes):,} bytes)")

    print("self-test OK")
    return 0


def _make_logger():
    """Return a log callable that survives running without a console.

    Launched through ``horizonw.exe`` (a GUI entry point) there is no stdout at
    all -- ``sys.stdout is None`` -- and a bare ``print`` would raise. In that
    case we append to ``%APPDATA%/horizon/horizon.log`` instead.
    """
    if _HAS_CONSOLE:
        return print

    import time

    log_path = config_path().parent / "horizon.log"

    def _log(message: str) -> None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"{stamp} {message}\n")
        except OSError:
            pass

    return _log


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.self_test:
        return _self_test()

    cfg, path = _resolve_config(args)

    if args.print_config:
        import json

        print(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False))
        print(f"# config path: {path}")
        return 0

    if args.preview:
        import time

        from . import metrics
        from .render import compose_image, save_comparison, save_preview

        w, h = args.size
        # real numbers, not invented ones: time an actual full-size compose
        started = time.perf_counter()
        compose_image(cfg, w, h)
        draw_ms = (time.perf_counter() - started) * 1000
        try:
            hud_text = metrics.snapshot(draw_ms).render()
        except Exception:  # non-Windows or restricted environment
            hud_text = None

        if args.compare:
            out = save_comparison(cfg, args.preview, w, h, hud_text=hud_text)
        else:
            out = save_preview(cfg, args.preview, w, h, notice=None, hud_text=hud_text)
        print(f"preview written to {out}")
        return 0

    if sys.platform != "win32":
        print("horizon only runs on Windows (layered window + per-pixel alpha).", file=sys.stderr)
        return 2

    log = _make_logger()

    # persist the resolved config so hotkey changes have somewhere to land
    try:
        save(cfg, path)
    except OSError as exc:
        log(f"[horizon] warning: could not write config ({exc!r}); changes will not persist")

    from .overlay import HorizonApp

    try:
        HorizonApp(cfg, path, log=log).run(duration=args.duration, with_tray=not args.no_tray)
    except Exception:
        import traceback

        log("[horizon] fatal:\n" + traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
