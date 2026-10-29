# Horizon

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md)

Horizon is a Windows utility for players who experience motion discomfort in 3D games. It places a static, click-through overlay above the screen: a vignette reduces peripheral visibility, while a fixed border and centre anchor provide visual references that do not move with the camera.

**[Download Horizon.exe](https://github.com/Peanut123467/horizon-overlay/releases/latest)** · Windows 10 / 11 · No installer · Apache-2.0

**v0.3.0:** redesigned control panel, screenshot comparison with a draggable centre handle, and a local visual preset library; removes nonessential captions and protects corrupted preset files. See the [release notes](docs/releases/v0.3.0.md)

![Standard preset comparison](docs/compare-standard.png)

> This is a visual aid, not a medical device. It does not diagnose or treat any condition and makes no claims of effectiveness. Stop playing if you feel unwell; seek professional advice for persistent symptoms. Avoid competitive online games: a separate overlay cannot guarantee acceptance by anti-cheat systems.

## Features and boundaries

- Adjustable vignette, border, centre reticle and optional dot grid.
- Optional reference triangles on all four edges, with outline/filled modes, base width, depth, outline thickness and opacity controls.
- Local control panel with live preview, screenshot comparison, up to 50 custom visual presets, colours, monitor selection and configuration import/export
- System tray controls, configurable global shortcuts and local break reminders.
- HUD showing the overlay monitor's refresh rate, this process's memory, system memory load and the latest full redraw time.
- No DLL injection, graphics hooks, game-process access, game-file changes, network requests, telemetry or health-data collection.

The graphical interface and tray labels are currently in Chinese. This README translates the instructions; it does not change the application's interface language. A [detailed panel guide in Chinese](docs/控制面板.md) is also available.

## Requirements and installation

Windows 10 or 11 is required for the overlay. Use **borderless windowed** or **windowed** mode in the game; exclusive fullscreen usually bypasses desktop composition and hides the overlay. One monitor is covered at a time. Python 3.10+ is required only for running from source.

### Prebuilt executable

1. Download `Horizon.exe` from [Releases](https://github.com/Peanut123467/horizon-overlay/releases/latest), or extract the Windows ZIP.
2. Keep it in a permanent folder, such as `D:\Tools\Horizon\`.
3. Double-click the executable to open **Horizon 控制台** (control panel).
4. Click **启动叠加层** (Start overlay). A tray icon and the screen overlay appear.

The single-file executable unpacks on launch. Startup time and memory use depend on the machine, resolution and whether the panel is open. Administrator privileges are not normally needed. Antivirus tools can flag PyInstaller executables; review the file and its source rather than assuming every detection is harmless.

### Run from source

```bat
git clone https://github.com/Peanut123467/horizon-overlay.git horizon-overlay
cd horizon-overlay
python -m venv .venv
.venv\Scripts\activate
pip install -e .
horizon --self-test
horizonw
```

`horizonw` opens the panel without a console window. `horizon` keeps a console for diagnostics. `self-test OK` confirms that the headless rendering checks passed.

## Everyday use

Start the overlay from the panel, then enter a game in borderless/windowed mode. Start with the gentle preset if you want less obstruction. Closing the panel leaves an already running overlay active in the tray.

| Chinese label | Meaning |
| --- | --- |
| 启动叠加层 / 停止叠加层 | Start / stop the overlay |
| 显示 / 隐藏 | Show / hide without exiting |
| 轻微 / 标准 / 强 | Gentle / standard / strong presets |
| 暗角 / 边框 / 中心准星 | Vignette / border / centre reticle |
| 四边三角 / 空心 / 实心 | Edge triangles / outline / filled |
| 锚点阵 / 统计面板 / 休息提醒 | Dot grid / stats HUD / break reminder |
| 恢复默认 / 导入配置 / 导出配置 | Reset / import / export configuration |
| 登录 Windows 后打开控制面板 | Open the panel after Windows sign-in |
| 打开控制面板 / 退出 | Open panel / quit |

Sliders update the preview and running overlay while you drag. Changes are coalesced to avoid a backlog; actual update speed depends on full-screen rendering cost. The final edit is flushed before the panel closes. Preset and external configuration updates preserve control focus, scroll position and drawer state.

Right-click the tray icon to open the panel, toggle effects, select a preset/colour, reload configuration, open the configuration folder or quit. Left-click the tray icon toggles visibility. Windows 11 may put the icon under the taskbar's `^` menu; drag it out or enable it in taskbar settings. The first overlay launch shows an eight-second tray hint.

Enable the sign-in option in the panel if desired. It opens the panel after sign-in; starting the overlay still requires the Start button. To exit normally, right-click the tray icon and choose **退出** (Quit), or stop it from the panel.

## Global shortcuts

| Default | Action | Fallback |
| --- | --- | --- |
| `Ctrl+Alt+H` | Show / hide | `Ctrl+Alt+F9` |
| `Ctrl+Alt+1` | Gentle preset | `Ctrl+Alt+F7` |
| `Ctrl+Alt+2` | Standard preset | `Ctrl+Alt+F8` |
| `Ctrl+Alt+3` | Strong preset | — |
| `Ctrl+Alt+T` | Toggle centre reticle | `Ctrl+Alt+F10` |
| `Ctrl+Alt+S` | Toggle stats HUD | `Ctrl+Alt+F11` |
| `Ctrl+Alt+C` | Cycle accent colour | `Ctrl+Alt+F12` |
| `Ctrl+Alt+Q` | Quit overlay | — |

Default shortcuts try their fallback when occupied. The startup log records the binding actually used. In the panel's **快捷键** section, click an action and press a Ctrl combination with a letter, digit or F1–F12; Alt and Shift are optional. Duplicate or occupied custom bindings are rejected. Esc cancels recording.

## Presets

| Name | Vignette start / strength | Border | Description |
| --- | --- | --- | --- |
| `gentle` | 0.55 / 0.35 | 6 px | Subtle peripheral shading |
| `standard` | 0.34 / 0.55 | 8 px | Default appearance |
| `strong` | 0.20 / 0.78 | 10 px | More obstruction; intended for short sessions |

Presets change the vignette, border, reticle and dot grid. They preserve the global colour, monitor, edge-triangle settings and other preferences. Reset restores all defaults, including disabled edge triangles.

## Configuration and recovery

The default file is `%APPDATA%\horizon\config.json`. Normal panel/tray changes save automatically. Use **重新载入配置** (Reload configuration) in the tray after editing the file yourself.

The file uses **strict JSON**, without comments or trailing commas. The following example shows the main defaults; omitted fields use their defaults.

```json
{
  "vignette": { "enabled": true, "inner": 0.34, "outer": 1.06, "strength": 0.55 },
  "frame": { "enabled": true, "inset": 26, "width": 8, "alpha": 90 },
  "triangles": { "enabled": false, "filled": false, "base": 50, "depth": 20, "width": 3, "alpha": 153 },
  "reticle": { "enabled": true, "size": 9, "gap": 9, "alpha": 150 },
  "grid": { "enabled": false, "spacing": 180, "radius": 2, "alpha": 16 },
  "session": { "enabled": true, "minutes": 60, "reminder_seconds": 3 },
  "stats": { "enabled": true, "position": "top-left", "font_size": 21, "alpha": 200, "refresh_ms": 1000 },
  "color": "#00FF66",
  "monitor": 0,
  "start_hidden": false
}
```

- Vignette radii are normalized distances: 0 is the centre and 1 is a corner. Reversed radii are sorted and the transition width is at least 0.05. The sliders enforce corresponding bounds. Strength ranges from 0 to 1.
- Border inset, thickness, reticle size/gap and grid spacing/radius are in pixels. Oversized border insets are limited to the available screen dimensions when drawn.
- Triangle `base` and `depth` are screen-relative percentages (1–100). `filled` chooses filled or outline mode; `width` affects the outline. Alpha values range from 0 to 255.
- `color` accepts `#RRGGBB` or `#RGB`. It colours reference shapes and HUD text, not the vignette's darkening mask.
- Monitor index 0 is the primary monitor. HUD positions are `top-left`, `top-right`, `bottom-left` and `bottom-right`; `refresh_ms` controls the update interval.
- `hotkeys` optionally maps actions such as `toggle`, `gentle`, `standard`, `strong`, `reticle`, `stats`, `color` and `quit` to shortcut strings.
- JSON booleans are recommended. Recognized string values include `true/false`, `1/0`, `yes/no` and `on/off`; invalid values keep the previous setting.

If parsing fails or the JSON root is not an object, the original file is moved to a unique `config.json.bak-<timestamp>-<id>` before defaults are used. A warning records the backup path. Read or backup failures stop recovery rather than allowing a silent overwrite. Normal saves keep the previous file as `config.json.bak`.

## HUD and break reminders

The HUD reads the refresh rate of the monitor containing the overlay, the overlay process's working set, system physical-memory load and the last full-screen redraw time. If the refresh rate cannot be read or the driver reports 0/1, that field is omitted. These figures are **not game FPS**. Horizon has no game-frame instrumentation or ETW consumer.

The HUD has its own small window. Full-screen composition runs when visible appearance, resolution or reminder text changes, including during slider input; identical content is deduplicated. Performance varies with hardware and resolution. The cache retains one vignette alpha image: about 7.9 MiB at 4K, excluding temporary arrays, backing surfaces and the panel process.

Break reminders use a local timer. The default interval is 60 minutes, with a three-second notice. The notice reports actual elapsed minutes for the current reminder cycle, even if you shorten the interval while running. It is a reminder, not a health assessment.

## Command line

```bat
horizon
horizon --overlay
horizon --preset strong --monitor 1
horizon --color "#00E5FF"
horizon --no-stats
horizon --preview out.png --compare
horizon --preview out.png --size 1200x675
horizon --self-test
horizon --print-config
horizon --duration 5 --no-tray
horizon --config my.json
horizon --version
```

`--preset`, `--color`, `--monitor` and `--no-stats` start a **temporary session**. The panel shows a temporary-session indicator and reads live settings; changes during that run are not written back to the saved configuration. Open the panel normally after stopping that session to make persistent changes. `--duration 0` schedules immediate exit after initialization.

## Troubleshooting and limitations

| Problem | What to check |
| --- | --- |
| Nothing over the game | Use borderless/windowed mode. If needed, try disabling fullscreen optimizations in the game's executable properties. |
| Missing tray icon | Open the taskbar's `^` menu or enable Horizon under system tray settings. |
| `horizon` command not found | Activate the virtual environment or check Python's Scripts directory in PATH. |
| Startup or panel error | Read `%APPDATA%\horizon\horizon.log`, or run `horizon` from a console. |
| Black control panel | Update WebView2 and the graphics driver. On affected systems, try the explicit workaround below. |
| Brief pause when changing effects | A full-screen image must be composed; cost grows with resolution. Check the HUD's measured redraw time. |
| HDR colour mismatch | The overlay uses SDR composition. |
| Multiple monitors | Only the selected monitor is covered; simultaneous coverage is not implemented. |

The GPU workaround is opt-in. In PowerShell, set the variable and launch Horizon from the same window:

```powershell
$env:HORIZON_WEBVIEW_ARGS = '--in-process-gpu'
.\Horizon.exe
```

This changes WebView2's process arrangement and is only intended for affected drivers, virtual machines or remote sessions. Close that PowerShell window or remove the environment variable to stop using the override.

No overlay can promise anti-cheat compatibility. Horizon does not alter the game's renderer or logic and does not implement per-frame animation, game FPS or simultaneous multi-monitor overlays.

## Development and contributions

```bat
pip install -e ".[dev]"
python -m pytest -q
node --test tests/live_updates.test.cjs
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python -m horizon --self-test
```

GitHub Actions checks Python 3.10 and 3.12 on Windows and Linux. Windows runs the full unit suite; Linux runs platform-independent configuration, shortcut validation and rendering tests, skipping Win32 integrations. This does not add Linux support to the graphical app. On Windows, `python tools/console_smoke.py` checks the real panel using isolated settings, and `python tools/integration_smoke.py` checks a separate overlay process; close existing Horizon windows before integration checks.

The main modules are `config.py` (validation/persistence), `render.py` (numpy/Pillow composition), `win32.py` (ctypes bindings), `overlay.py` (windows, hotkeys and timers), `metrics.py` (local measurements), `console/` (panel), and `tray.py` (tray commands). To build the executable, install PyInstaller and run `python tools/build_exe.py`.

Planned work includes an ETW-based game-FPS implementation, automatic configuration reload, additional mask shapes, simultaneous multi-monitor coverage and lower memory use. These are roadmap items, not current features.

Bug reports, presets, compatibility feedback and documentation improvements are welcome in [Issues](https://github.com/Peanut123467/horizon-overlay/issues). Do not include health data or efficacy claims. Licensed under [Apache-2.0](LICENSE).
