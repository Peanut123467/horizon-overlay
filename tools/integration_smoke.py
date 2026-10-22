"""Exercise a real, isolated overlay process through the control-panel API."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from horizon import ipc, launcher  # noqa: E402
from horizon.config import load  # noqa: E402
from horizon.console.app import Api  # noqa: E402


def main():
    if ipc.find_overlay():
        raise SystemExit(
            "Close the existing overlay before running this isolated integration check."
        )
    (ROOT / ".runtime").mkdir(exist_ok=True)
    api = Api(Path(tempfile.mkdtemp(dir=ROOT / ".runtime")) / "config.json")
    original_launch = launcher.launch
    children = []

    def launch(*args):
        child = original_launch(*args, "--duration", "40", "--no-tray")
        children.append(child)
        return child

    launcher.launch = launch
    try:
        assert api.start_overlay()["overlay_alive"], "overlay failed to start"
        print("PASS real overlay launched", flush=True)
        api.patch({"frame": {"width": 14}})
        api.patch({"vignette": {"strength": 0.81}})
        saved = load(api._cfg_path)
        assert saved.frame.width == 14 and saved.vignette.strength == 0.81
        print("PASS sequential IPC changes preserved on disk", flush=True)
        subprocess.run(
            launcher.command("--overlay", "--config", str(api._cfg_path), "--color", "#FF0000"),
            check=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert load(api._cfg_path).color == saved.color
        print("PASS duplicate process leaves active config intact", flush=True)
        api.preset("strong")
        assert load(api._cfg_path).vignette.strength == 0.78
        api.preset("standard")
        assert load(api._cfg_path).vignette.strength == 0.55
        print("PASS live presets restored defaults", flush=True)
        api.patch({"hotkeys": {"toggle": "Ctrl+Alt+Shift+F6"}})
        assert load(api._cfg_path).hotkeys["toggle"] == "Ctrl+Alt+Shift+F6"
        from horizon import win32

        occupied = win32.register_hotkey(None, 0xBFFF, 7, 0x74)
        if occupied:
            try:
                try:
                    api.patch({"hotkeys": {"reticle": "Ctrl+Alt+Shift+F5"}})
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("occupied hotkey was accepted")
                assert load(api._cfg_path).hotkeys["reticle"] == "Ctrl+Alt+T"
            finally:
                win32.user32.UnregisterHotKey(None, 0xBFFF)
            print("PASS live hotkey rebind and conflict rollback", flush=True)
        else:
            raise AssertionError("integration test hotkey already occupied")
        api.toggle_overlay()
        api.toggle_overlay()
        print("PASS overlay toggle commands", flush=True)
        assert not api.stop_overlay()["overlay_alive"]
        children[0].wait(timeout=5)
        print("PASS clean overlay shutdown", flush=True)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
        launcher.launch = original_launch


if __name__ == "__main__":
    main()
