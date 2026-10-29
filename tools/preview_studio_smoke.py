"""Exercise the real WebView bridge using an isolated config and a generated still.

Set HORIZON_STUDIO_HOLD=1 to leave the test window open for visual inspection
after checks finish. No user's config, screenshots or overlay are modified.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import webview  # noqa: E402
from PIL import Image  # noqa: E402

from horizon import ipc  # noqa: E402
from horizon.config import load  # noqa: E402
from horizon.console.app import Api, install_close_guard, load_html, prepare_webview_env  # noqa: E402


def wait(window, expression, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = window.evaluate_js(expression)
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(f"Timed out: {expression}")


def probe(window, api, screenshot):
    try:
        assert window.events.loaded.wait(20), "window load"
        wait(window, "window.__horizonReady")
        wait(window, "document.querySelector('#preview').naturalWidth > 0")
        check(
            "preview and original align",
            window.evaluate_js(
                "document.querySelector('#preview').naturalWidth === document.querySelector('#preview-original').naturalWidth"
            ),
        )
        window.evaluate_js(
            "document.querySelector('#compare-slider').value=28;document.querySelector('#compare-slider').dispatchEvent(new Event('input'))"
        )
        check(
            "comparison responds",
            window.evaluate_js(
                "document.querySelector('#preview-stage').style.getPropertyValue('--split')"
            )
            == "28%",
        )
        window.evaluate_js("document.querySelector('#btn-compare').click()")
        check(
            "comparison toggles off",
            window.evaluate_js(
                "document.querySelector('#preview-stage').classList.contains('compare-off')"
            ),
        )
        window.evaluate_js("document.querySelector('#btn-compare').click()")

        window.evaluate_js("document.querySelector('#btn-profile-save').click()")
        wait(window, "document.querySelector('#profile-dialog').open")
        window.evaluate_js(
            "document.querySelector('#profile-name').value='夜间探索';document.querySelector('#profile-form').requestSubmit()"
        )
        wait(
            window,
            "document.querySelectorAll('.profile-card').length===1 && !document.querySelector('#profile-dialog').open",
        )
        check("named preset persists", api.profiles()[0]["name"] == "夜间探索")
        window.evaluate_js("document.querySelector('.profile-actions button').click()")
        wait(window, "document.querySelectorAll('.profile-card').length===2")
        check("duplicate has independent ID", len({p["id"] for p in api.profiles()}) == 2)
        window.evaluate_js("document.querySelectorAll('.profile-actions')[1].children[1].click()")
        wait(window, "document.querySelector('#profile-dialog').open")
        window.evaluate_js(
            "document.querySelector('#profile-name').value='暮色漫游';document.querySelector('#profile-form').requestSubmit()"
        )
        wait(window, "!document.querySelector('#profile-dialog').open")
        check("rename persists", api.profiles()[1]["name"] == "暮色漫游")

        state = api.patch({"frame": {"width": 22}, "session": {"minutes": 37}})
        window.evaluate_js(f"renderState({json.dumps(state)})")
        window.evaluate_js("document.querySelector('.profile-apply').click()")
        wait(window, "cfg.frame.width===8")
        check("apply preserves timer", load(api._cfg_path).session.minutes == 37)
        window.evaluate_js("document.querySelector('.profile-actions').children[2].click()")
        wait(window, "document.querySelector('#profile-dialog').open")
        check("delete asks confirmation", len(api.profiles()) == 2)
        window.evaluate_js("document.querySelector('#dialog-cancel').click()")
        check("cancel keeps preset", len(api.profiles()) == 2)
        window.evaluate_js("document.querySelector('.profile-actions').children[2].click()")
        wait(window, "document.querySelector('#profile-dialog').open")
        window.evaluate_js("document.querySelector('#profile-form').requestSubmit()")
        wait(window, "document.querySelectorAll('.profile-card').length===1")
        check("confirmed delete persists", len(api.profiles()) == 1)

        # Exercise the real decoder/API, replacing only the operating-system picker.
        api._window = SimpleNamespace(create_file_dialog=lambda *args, **kw: [str(screenshot)])
        window.evaluate_js("document.querySelector('#btn-preview-import').click()")
        wait(window, "document.querySelector('#preview-name').textContent==='wide-test.png'")
        wait(
            window,
            "document.querySelector('#preview').naturalWidth / document.querySelector('#preview').naturalHeight === 4",
        )
        check(
            "wide screenshot remains aligned",
            window.evaluate_js(
                "document.querySelector('#preview').naturalWidth===document.querySelector('#preview-original').naturalWidth"
            ),
        )
        api._window = SimpleNamespace(create_file_dialog=lambda *args, **kw: None)
        window.evaluate_js("document.querySelector('#btn-preview-import').click()")
        time.sleep(0.3)
        check(
            "cancel retains screenshot",
            window.evaluate_js("document.querySelector('#preview-name').textContent")
            == "wide-test.png",
        )
        window.evaluate_js("document.querySelector('#btn-preview-reset').click()")
        wait(window, "document.querySelector('#preview-name').textContent==='模拟场景'")
        check(
            "reset restores scene",
            window.evaluate_js(
                "document.querySelector('#preview').naturalWidth / document.querySelector('#preview').naturalHeight"
            )
            == 16 / 9,
        )
        api._window = window

        check(
            "UI theme independent of overlay color",
            window.evaluate_js(
                "getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"
            )
            == "#efb184",
        )
        check("no script errors", not window.evaluate_js("window.__horizonErrors"))
        check(
            "no horizontal overflow",
            window.evaluate_js("document.documentElement.scrollWidth<=innerWidth"),
        )
        window.resize(860, 600)
        time.sleep(0.4)
        check(
            "minimum window has no horizontal overflow",
            window.evaluate_js("document.documentElement.scrollWidth<=innerWidth"),
        )
        check(
            "minimum window keeps parameter values visible",
            window.evaluate_js(
                "[...document.querySelectorAll('.field output')].filter(o=>o.getBoundingClientRect().width>0).every(o=>o.getBoundingClientRect().right<=innerWidth)"
            ),
        )
        window.resize(1280, 820)
        print("VISUAL_READY", flush=True)
        if os.environ.get("HORIZON_STUDIO_HOLD"):
            for _ in range(180):
                time.sleep(1)
    except Exception:
        import traceback

        check("probe completed", False)
        traceback.print_exc()
    finally:
        with contextlib.suppress(Exception):
            window.destroy()


results = []


def check(name, ok):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}", flush=True)


if __name__ == "__main__":
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="preview-studio-", dir=runtime))
    screenshot = directory / "wide-test.png"
    Image.new("RGB", (1600, 400), (85, 115, 145)).save(screenshot)
    ipc.find_overlay = lambda: 0
    api = Api(directory / "config.json")
    prepare_webview_env()
    window = webview.create_window(
        "Horizon Studio QA",
        html=load_html(),
        js_api=api,
        width=1280,
        height=820,
        min_size=(860, 600),
        background_color="#101820",
    )
    api._window = window
    install_close_guard(window)
    threading.Thread(target=probe, args=(window, api, screenshot), daemon=True).start()
    webview.start()
    print(f"{sum(results)}/{len(results)} passed", flush=True)
    raise SystemExit(0 if results and all(results) else 1)
