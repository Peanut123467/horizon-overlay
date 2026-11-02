"""Exercise v0.4 controls in a real WebView with isolated configuration."""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import webview  # noqa: E402
from preview_studio_smoke import wait  # noqa: E402

from horizon import ipc  # noqa: E402
from horizon.console.app import Api, install_close_guard, load_html, prepare_webview_env  # noqa: E402


def probe(window, api, directory, results):
    def check(name, ok):
        assert ok, name
        results.append(name)
        print(f"PASS {name}", flush=True)

    def js(source):
        return window.evaluate_js(source)

    def record(code, key):
        js(
            "document.querySelector('.profile-hotkey').focus();document.querySelector('.profile-hotkey').click()"
        )
        js(
            "document.querySelector('.profile-hotkey').dispatchEvent(new KeyboardEvent('keydown',"
            + json.dumps(
                {"key": key, "code": code, "ctrlKey": True, "altKey": True, "bubbles": True}
            )
            + "))"
        )

    try:
        assert window.events.loaded.wait(20)
        wait(window, "window.__horizonReady")
        wait(window, "document.querySelectorAll('.profile-card').length===1")
        record("KeyJ", "j")
        wait(window, "document.querySelector('.profile-hotkey').textContent==='Ctrl+Alt+J'")
        identifier = api.profiles()[0]["id"]
        check(
            "record persists through real bridge",
            api.state()["config"]["profile_hotkeys"] == {identifier: "Ctrl+Alt+J"},
        )
        record("KeyH", "h")
        wait(window, "!document.querySelector('.profile-hotkey').disabled")
        check(
            "duplicate rejection restores displayed binding",
            js("document.querySelector('.profile-hotkey').textContent") == "Ctrl+Alt+J",
        )
        check(
            "duplicate rejection preserves saved binding",
            api.state()["config"]["profile_hotkeys"][identifier] == "Ctrl+Alt+J",
        )
        check(
            "duplicate error is explained",
            js("document.querySelector('#feedback').textContent.includes('重复')"),
        )
        js("window.__horizonErrors=[]")
        js(
            "document.querySelector('.profile-hotkey').focus();document.querySelector('.profile-hotkey').click();document.querySelector('.profile-hotkey').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"
        )
        check(
            "Escape cancels recording",
            js("document.querySelector('.profile-hotkey').dataset.recording") == "false",
        )
        js("document.querySelector('.profile-hotkey-clear').click()")
        wait(window, "document.querySelector('.profile-hotkey').textContent==='设置快捷键'")
        check("clear removes saved binding", not api.state()["config"]["profile_hotkeys"])
        path = directory / "share.json"
        api._window = SimpleNamespace(create_file_dialog=lambda *a, **kw: [str(path)])
        js(
            "[...document.querySelectorAll('.profile-actions button')].find(b=>b.textContent==='导出').click()"
        )
        deadline = time.monotonic() + 10
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        check(
            "export produces a standalone preset",
            set(json.loads(path.read_text(encoding="utf-8")))
            == {"format", "version", "name", "visuals"},
        )
        wait(
            window,
            "[...document.querySelectorAll('.profile-actions button')].every(b=>!b.disabled)",
        )
        js("document.querySelector('#btn-profile-import').click()")
        wait(window, "document.querySelectorAll('.profile-card').length===2")
        check(
            "import resolves names with independent IDs",
            len({p["id"] for p in api.profiles()}) == 2
            and api.profiles()[1]["name"] == "夜间探索 · 导入 1",
        )
        api._window = SimpleNamespace(create_file_dialog=lambda *a, **kw: None)
        js("document.querySelector('#btn-profile-import').click()")
        wait(window, "!document.querySelector('#btn-profile-import').disabled")
        check("cancel import preserves library", len(api.profiles()) == 2)
        record("KeyJ", "j")
        wait(window, "document.querySelector('.profile-hotkey').textContent==='Ctrl+Alt+J'")
        js(
            "[...document.querySelectorAll('.profile-actions button')].find(b=>b.textContent==='删除').click()"
        )
        wait(window, "document.querySelector('#profile-dialog').open")
        js("document.querySelector('#profile-form').requestSubmit()")
        wait(window, "document.querySelectorAll('.profile-card').length===1")
        check("confirmed delete clears binding", not api.state()["config"]["profile_hotkeys"])
        check("no unexpected script errors", not js("window.__horizonErrors"))
        for width, height in ((1280, 820), (860, 600)):
            window.resize(width, height)
            time.sleep(0.3)
            check(
                f"layout fits {width}px window",
                js(
                    "document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('.library button')].every(b=>b.getBoundingClientRect().right<=innerWidth)"
                ),
            )
        api._window = window
    except Exception:
        import traceback

        results.append(False)
        traceback.print_exc()
    finally:
        with contextlib.suppress(Exception):
            window.destroy()


if __name__ == "__main__":
    directory = Path(tempfile.mkdtemp(prefix="preset-shortcuts-", dir=ROOT / ".runtime"))
    ipc.find_overlay = lambda: 0
    api = Api(directory / "config.json")
    # This probe does not change or inspect the user's login startup settings.
    api.startup = lambda enabled=None: False
    api.save_profile("夜间探索")
    prepare_webview_env()
    window = webview.create_window(
        "Horizon v0.4 QA", html=load_html(), js_api=api, width=1280, height=820, min_size=(860, 600)
    )
    api._window = window
    install_close_guard(window)
    results = []
    threading.Thread(target=probe, args=(window, api, directory, results), daemon=True).start()
    webview.start()
    raise SystemExit(0 if results and all(results) else 1)
