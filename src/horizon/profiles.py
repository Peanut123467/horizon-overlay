"""Local visual presets, deliberately separate from machine/session settings."""

from __future__ import annotations

import json
import math
import os
import unicodedata
from pathlib import Path
from uuid import uuid4

from .config import HorizonConfig, apply_patch

VISUAL_KEYS = ("vignette", "frame", "triangles", "reticle", "grid", "color")
MAX_PROFILES = 50


def visual_settings(cfg: HorizonConfig) -> dict:
    data = cfg.to_dict()
    return {key: data[key] for key in VISUAL_KEYS}


def checked_name(name: str) -> str:
    if not isinstance(name, str) or any(unicodedata.category(c).startswith("C") for c in name):
        raise ValueError("预设名称请使用 1–40 个可见字符")
    name = name.strip()
    if not 1 <= len(name) <= 40:
        raise ValueError("预设名称请使用 1–40 个可见字符")
    return name


def checked_visuals(raw: dict) -> dict:
    """Persisted presets must be complete and valid, never silently repaired."""
    template = visual_settings(HorizonConfig())
    if set(raw) != set(template):
        raise ValueError
    for key, expected in template.items():
        value = raw[key]
        if isinstance(expected, dict):
            if not isinstance(value, dict) or set(value) != set(expected):
                raise ValueError
            for field, default in expected.items():
                actual = value[field]
                if isinstance(default, float):
                    if type(actual) not in (float, int) or not math.isfinite(actual):
                        raise ValueError
                elif type(actual) is not type(default):
                    raise ValueError
        elif not isinstance(value, str):
            raise ValueError
    normalized = visual_settings(apply_patch(HorizonConfig(), raw))
    if normalized != raw:
        raise ValueError
    return normalized


class ProfileStore:
    """Read before every mutation; never replace an unreadable library."""

    def __init__(self, path: Path):
        self.path = path

    def list(self) -> list[dict]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            raise ValueError(f"无法读取预设库，请保留文件并检查：{self.path}") from exc
        try:
            if not isinstance(raw, dict) or raw.get("version") != 1:
                raise ValueError
            profiles = raw["profiles"]
            if not isinstance(profiles, list) or len(profiles) > MAX_PROFILES:
                raise ValueError
            ids, names = set(), set()
            for entry in profiles:
                identifier = entry["id"]
                if not isinstance(identifier, str) or not identifier or identifier in ids:
                    raise ValueError
                name = checked_name(entry["name"])
                if name.casefold() in names or not isinstance(entry["visuals"], dict):
                    raise ValueError
                entry["name"] = name
                entry["visuals"] = checked_visuals(entry["visuals"])
                ids.add(identifier)
                names.add(name.casefold())
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"预设库格式无效，原文件已保留：{self.path}") from exc
        return profiles

    def _write(self, profiles: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(
                    {"version": 1, "profiles": profiles}, stream, ensure_ascii=False, indent=2
                )
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _find(profiles: list[dict], identifier: str) -> dict:
        for entry in profiles:
            if entry["id"] == identifier:
                return entry
        raise ValueError("找不到这个预设，请刷新预设库后重试")

    @staticmethod
    def _unique(profiles: list[dict], name: str, identifier: str | None = None) -> str:
        name = checked_name(name)
        if any(p["name"].casefold() == name.casefold() and p["id"] != identifier for p in profiles):
            raise ValueError("已有同名预设，请换一个名称")
        return name

    def save(self, name: str, cfg: HorizonConfig) -> None:
        profiles = self.list()
        name = self._unique(profiles, name)
        if len(profiles) >= MAX_PROFILES:
            raise ValueError("最多保存 50 个预设，请先删除不再使用的方案")
        profiles.append({"id": uuid4().hex, "name": name, "visuals": visual_settings(cfg)})
        self._write(profiles)

    def get(self, identifier: str) -> dict:
        return self._find(self.list(), identifier)["visuals"]

    def rename(self, identifier: str, name: str) -> None:
        profiles = self.list()
        entry = self._find(profiles, identifier)
        entry["name"] = self._unique(profiles, name, identifier)
        self._write(profiles)

    def duplicate(self, identifier: str) -> None:
        profiles = self.list()
        entry = self._find(profiles, identifier)
        if len(profiles) >= MAX_PROFILES:
            raise ValueError("最多保存 50 个预设，请先删除不再使用的方案")
        for number in range(1, MAX_PROFILES + 2):
            suffix = f" · 副本 {number}"
            name = entry["name"][: 40 - len(suffix)] + suffix
            if all(p["name"].casefold() != name.casefold() for p in profiles):
                break
        profiles.append({"id": uuid4().hex, "name": name, "visuals": entry["visuals"]})
        self._write(profiles)

    def delete(self, identifier: str) -> None:
        profiles = self.list()
        entry = self._find(profiles, identifier)
        profiles.remove(entry)
        self._write(profiles)
