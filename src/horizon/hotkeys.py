"""Validation shared by configuration, the panel and Windows registration."""

from __future__ import annotations

DEFAULT_HOTKEYS = {
    "toggle": "Ctrl+Alt+H",
    "gentle": "Ctrl+Alt+1",
    "standard": "Ctrl+Alt+2",
    "strong": "Ctrl+Alt+3",
    "reticle": "Ctrl+Alt+T",
    "quit": "Ctrl+Alt+Q",
    "stats": "Ctrl+Alt+S",
    "color": "Ctrl+Alt+C",
}
ACTIONS = tuple(DEFAULT_HOTKEYS)
LABELS = dict(
    zip(
        ACTIONS,
        (
            "显示 / 隐藏",
            "轻微预设",
            "标准预设",
            "强预设",
            "中心准星",
            "退出叠加层",
            "统计面板",
            "切换颜色",
        ),
        strict=True,
    )
)


def parse_binding(text: str) -> tuple[int, int]:
    if not isinstance(text, str):
        raise ValueError("快捷键格式无效")
    parts = text.split("+")
    modifiers = {"Ctrl": 2, "Alt": 1, "Shift": 4}
    if len(parts) < 2 or "Ctrl" not in parts[:-1] or len(set(parts)) != len(parts):
        raise ValueError("请使用 Ctrl 加字母、数字或 F1–F12，可同时按 Alt、Shift")
    mods = 0
    for part in parts[:-1]:
        if part not in modifiers:
            raise ValueError("不支持的修饰键")
        mods |= modifiers[part]
    key = parts[-1]
    if len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("请选择字母、数字或 F1–F12")
    return mods, vk


def validate_bindings(bindings: dict) -> dict[str, str]:
    if not isinstance(bindings, dict):
        raise ValueError("快捷键配置必须是对象")
    result = {
        **DEFAULT_HOTKEYS,
        **{key: value for key, value in bindings.items() if key in DEFAULT_HOTKEYS},
    }
    parsed = [parse_binding(value) for value in result.values()]
    if len(set(parsed)) != len(parsed):
        raise ValueError("快捷键重复，请为每个操作设置不同的组合")
    return result
