"""Smoke test for the control panel.

WebView2 paints through DirectComposition, which neither BitBlt nor
``PrintWindow(PW_RENDERFULLCONTENT)`` can capture -- a screenshot of the window
comes back black even when the page is fine. So this drives the page through
``evaluate_js`` and asserts on DOM state and on the config that lands on disk.

    python tools/console_smoke.py
"""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import webview  # noqa: E402

from horizon import ipc  # noqa: E402
from horizon.config import load  # noqa: E402
from horizon.console.app import Api, install_close_guard, load_html, prepare_webview_env  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))


def wait_for(window, expression: str, timeout: float = 8.0):
    """Poll a JS expression until it is truthy."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            value = window.evaluate_js(expression)
        except Exception:
            value = None
        if value:
            return value
        time.sleep(0.2)
    return None


def probe(window) -> None:
    try:
        _probe(window)
    except Exception:
        import traceback

        check("探针正常完成", False, traceback.format_exc())
    finally:
        with contextlib.suppress(Exception):
            window.destroy()


def _probe(window) -> None:
    if not window.events.loaded.wait(20):
        check("窗口加载", False, "20 秒超时")
        return
    if not wait_for(window, "window.__horizonReady", timeout=15):
        check("界面初始化", False, str(window.evaluate_js("window.__horizonErrors")))
        return

    groups = wait_for(window, "document.querySelectorAll('.group').length")
    check("页面加载并渲染出参数分组", bool(groups), f"分组数={groups}")

    errors = window.evaluate_js("window.__horizonErrors || []")
    check("没有 JS 运行时错误", not errors, str(errors))

    wait_for(
        window,
        "document.querySelector('#preview').complete && document.querySelector('#preview').naturalWidth > 0",
    )
    preview = window.evaluate_js("document.querySelector('#preview').src.slice(0, 22)")
    check("预览图已渲染", str(preview).startswith("data:image/png;base64"), str(preview))

    status = window.evaluate_js("document.querySelector('#status').textContent")
    check("状态徽标有文字", bool(status), str(status))

    swatches = window.evaluate_js("document.querySelectorAll('.swatch').length")
    check("调色板有 5 个色块", swatches == 5, f"色块数={swatches}")

    outputs = window.evaluate_js("document.querySelectorAll('.field output').length")
    check("滑块右侧有数值栏", outputs and outputs > 0, f"output 数={outputs}")
    first = window.evaluate_js("(document.querySelector('.field output')||{}).textContent || ''")
    check("数值栏有内容", bool(str(first).strip()), repr(first))
    cols = window.evaluate_js(
        "getComputedStyle(document.querySelector('.field')).gridTemplateColumns"
    )
    check("字段是三列布局", len(str(cols).split()) == 3, str(cols))
    bounds = window.evaluate_js(
        "(() => { const o=document.querySelector('.field output'); const r=o.getBoundingClientRect(); return {width:r.width,right:r.right,limit:innerWidth}; })()"
    )
    check(
        "数值栏位于可见区域",
        bounds["width"] >= 50 and bounds["right"] <= bounds["limit"],
        str(bounds),
    )

    # -- change a slider and confirm it reaches the config on disk -----------
    window.evaluate_js(
        "(() => { const i = document.querySelector('.field[data-field=\"strength\"] input');"
        " i.value = 0.9; i.dispatchEvent(new Event('input', { bubbles: true })); })()"
    )
    time.sleep(0.8)
    saved = json.loads(Path(api._cfg_path).read_text(encoding="utf-8"))
    check(
        "滑块改动写入配置",
        abs(saved["vignette"]["strength"] - 0.9) < 1e-6,
        str(saved["vignette"]["strength"]),
    )

    # -- click a swatch and confirm the colour changes ----------------------
    window.evaluate_js("document.querySelectorAll('.swatch')[1].click()")
    time.sleep(0.8)
    saved = json.loads(Path(api._cfg_path).read_text(encoding="utf-8"))
    check("点击色块切换颜色", saved["color"].upper() == "#00E5FF", saved["color"])

    # -- preset button ------------------------------------------------------
    window.evaluate_js("document.querySelector('.btn-preset[data-preset=\"strong\"]').click()")
    time.sleep(1.0)
    saved = json.loads(Path(api._cfg_path).read_text(encoding="utf-8"))
    check(
        "预设按钮生效",
        abs(saved["vignette"]["strength"] - 0.78) < 1e-6,
        str(saved["vignette"]["strength"]),
    )

    window.evaluate_js("document.querySelector('.btn-preset[data-preset=\"standard\"]').click()")
    time.sleep(0.8)
    saved = json.loads(Path(api._cfg_path).read_text(encoding="utf-8"))
    check("标准预设恢复标准数值", saved["vignette"]["strength"] == 0.55, str(saved))
    window.evaluate_js(
        "document.querySelector('.field[data-group=stats][data-field=position] .select-trigger').scrollIntoView({block:'center'})"
    )
    time.sleep(0.15)
    dropdown_motion = window.evaluate_js(
        "(() => { const b=document.querySelector('.field[data-group=stats][data-field=position] .select-trigger'); b.click(); const p=document.querySelector('.select-popup'); return !!p && (p.getAnimations().length > 0 || matchMedia('(prefers-reduced-motion: reduce)').matches); })()"
    )
    check("下拉选项具有抽拉展开动画", dropdown_motion)
    time.sleep(0.5)
    check(
        "下拉菜单不被参数面板裁切",
        bool(
            window.evaluate_js(
                "(() => { const r=document.querySelector('.select-popup').getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight && r.height>80; })()"
            )
        ),
    )
    window.evaluate_js("document.querySelectorAll('.select-popup .select-option')[1].click()")
    time.sleep(0.6)
    check("下拉选择写入配置", load(api._cfg_path).stats.position == "top-right")
    check(
        "下拉选择后平滑关闭",
        window.evaluate_js("document.querySelectorAll('.select-popup').length") == 0,
    )
    window.evaluate_js(
        "(() => { const b=document.querySelector('.field[data-group=stats][data-field=position] .select-trigger'); b.click(); b.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape',bubbles:true})); })()"
    )
    wait_for(window, "document.querySelectorAll('.select-popup').length === 0", timeout=3)
    check(
        "下拉框可通过 Escape 关闭",
        window.evaluate_js("document.querySelectorAll('.select-popup').length") == 0,
    )
    window.evaluate_js("document.querySelector('.controls').scrollTop=0")
    time.sleep(0.2)
    check(
        "预设切换保留显示器",
        bool(window.evaluate_js("document.querySelector('.group[data-group=display]')")),
    )

    # Capture this WebView directly; never capture the user's desktop.
    from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
    from System import Action
    from System.IO import MemoryStream

    stream = MemoryStream()
    tasks = []
    window.native.Invoke(
        Action(
            lambda: tasks.append(
                window.native.webview.CoreWebView2.CapturePreviewAsync(
                    CoreWebView2CapturePreviewImageFormat.Png, stream
                )
            )
        )
    )
    tasks[0].GetAwaiter().GetResult()
    (ROOT / "docs" / "_console-verified.png").write_bytes(bytes(stream.ToArray()))
    stream.Dispose()

    errors = window.evaluate_js("window.__horizonErrors || []")
    check("交互过程无 JS 错误", not errors, str(errors))
    jelly = window.evaluate_js(
        "(() => { const b=document.querySelector('.group[data-group=vignette] .group-toggle'); b.click(); return b.getAnimations().length > 0 || matchMedia('(prefers-reduced-motion: reduce)').matches; })()"
    )
    check("按钮具有果冻回弹动画", jelly)
    time.sleep(0.5)
    closed = window.evaluate_js(
        "document.querySelector('#drawer-vignette').getBoundingClientRect().height"
    )
    check("参数抽屉能够收起", closed < 1, str(closed))
    window.evaluate_js(
        "document.querySelector('.group[data-group=vignette] .group-toggle').click()"
    )
    time.sleep(0.5)
    opened = window.evaluate_js(
        "document.querySelector('#drawer-vignette').getBoundingClientRect().height"
    )
    check("参数抽屉能够展开", opened > 80, str(opened))
    check(
        "抽屉包含平滑高度过渡",
        bool(
            window.evaluate_js(
                "getComputedStyle(document.querySelector('#drawer-vignette')).transitionProperty.includes('grid-template-rows')"
            )
        ),
    )
    window.evaluate_js(
        "(() => { const b=document.querySelector('[data-action=toggle]'); b.click(); b.dispatchEvent(new KeyboardEvent('keydown', {key:'9',code:'Digit9',ctrlKey:true,altKey:true,shiftKey:true,bubbles:true})); })()"
    )
    time.sleep(0.8)
    saved = json.loads(Path(api._cfg_path).read_text(encoding="utf-8"))
    check("快捷键录制保存", saved["hotkeys"]["toggle"] == "Ctrl+Alt+Shift+9", str(saved["hotkeys"]))
    window.evaluate_js(
        "(() => { const b=document.querySelector('[data-action=toggle]'); b.click(); b.dispatchEvent(new KeyboardEvent('keydown', {key:'q',code:'KeyQ',ctrlKey:true,altKey:true,bubbles:true})); })()"
    )
    time.sleep(0.5)
    saved = json.loads(Path(api._cfg_path).read_text(encoding="utf-8"))
    check("重复快捷键被拒绝", saved["hotkeys"]["toggle"] == "Ctrl+Alt+Shift+9")
    check(
        "快捷键冲突有可见提示",
        "重复" in str(window.evaluate_js("document.querySelector('#feedback').textContent")),
    )
    window.evaluate_js(
        "window.__horizonErrors=[]; (() => { const i=document.querySelector('.field[data-field=strength] input'); i.value=.67; i.dispatchEvent(new Event('input')); })()"
    )


if __name__ == "__main__":
    (ROOT / ".runtime").mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=ROOT / ".runtime")) / "config.json"
    ipc.find_overlay = lambda: 0  # isolated checks never modify a running user's overlay
    api = Api()
    api._cfg_path = tmp  # never touch the real user config

    prepare_webview_env()
    window = webview.create_window(
        "Horizon smoke", html=load_html(), js_api=api, width=1000, height=720
    )
    api._window = window
    install_close_guard(window)
    threading.Thread(target=probe, args=(window,), daemon=True).start()
    webview.start()
    saved = load(api._cfg_path)
    check("关闭窗口前保存最后一次滑块操作", saved.vignette.strength == 0.67)

    print()
    failed = 0
    for name, ok, detail in checks:
        print(
            f"  {'PASS' if ok else 'FAIL'}  {name}"
            + (f"   ({detail})" if detail and not ok else "")
        )
        failed += 0 if ok else 1
    print(f"\n{len(checks) - failed}/{len(checks)} 通过")
    raise SystemExit(1 if failed or not checks else 0)
