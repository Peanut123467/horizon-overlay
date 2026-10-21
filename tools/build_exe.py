"""Build ``dist/Horizon.exe`` -- a single-file, double-clickable launcher.

    python tools/build_exe.py

Notes
-----
* ``--windowed`` means no console window: this is a tray-resident app, so
  diagnostics go to ``%APPDATA%/horizon/horizon.log`` instead of stdout.
* ``--onefile`` produces a single ~40-60 MB exe. First launch unpacks to a temp
  directory, so expect a 1-3 s cold start.
* PyInstaller output is frequently flagged by antivirus heuristics. That is a
  known false positive of the bootloader, not of this code. If you would rather
  avoid it, run from source instead (see README).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build() -> int:
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "Horizon",
        "--icon",
        str(ROOT / "assets" / "horizon.ico"),
        "--paths",
        str(ROOT / "src"),
        "--collect-submodules",
        "pystray",
        str(ROOT / "tools" / "entry.py"),
    ]
    print(" ".join(args))
    return subprocess.call(args, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(build())
