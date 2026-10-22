"""Control panel: a pywebview window that drives the overlay over IPC."""

from __future__ import annotations

__all__ = ["run_console"]


def run_console(**kwargs) -> int:
    from .app import run

    return run(**kwargs)
