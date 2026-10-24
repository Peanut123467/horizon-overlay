import json
from pathlib import Path

import pytest

from horizon.config import default_config, load, save


@pytest.mark.parametrize("raw", [b'{"color":"#FFFFFF",}', b"[]", b"\xff\xfe"])
def test_invalid_config_is_preserved_before_defaults_are_saved(tmp_path, raw, caplog):
    path = tmp_path / "config.json"
    path.write_bytes(raw)
    recovered = load(path)
    save(recovered, path)
    backups = list(tmp_path.glob("config.json.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw
    assert json.loads(path.read_text()) == default_config().to_dict()
    assert str(backups[0]) in caplog.text


def test_failed_recovery_backup_leaves_original_untouched(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    raw = b'{"color":"#FFFFFF",}'
    path.write_bytes(raw)

    def denied(*args, **kwargs):
        raise PermissionError("backup denied")

    monkeypatch.setattr(Path, "rename", denied)
    with pytest.raises(OSError):
        load(path)
    assert path.read_bytes() == raw


def test_read_failure_does_not_return_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"color":"#FFFFFF"}')

    def denied(*args, **kwargs):
        raise PermissionError("read denied")

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(OSError):
        load(path)


def test_save_keeps_previous_configuration(tmp_path):
    path = tmp_path / "config.json"
    cfg = default_config()
    cfg.color = "#FFFFFF"
    save(cfg, path)
    cfg.color = "#ABCDEF"
    save(cfg, path)
    assert load(path).color == "#ABCDEF"
    assert load(path.with_name("config.json.bak")).color == "#FFFFFF"


def test_identical_save_does_not_replace_useful_backup(tmp_path):
    path = tmp_path / "config.json"
    cfg = default_config()
    save(cfg, path)
    cfg.color = "#ABCDEF"
    save(cfg, path)
    save(cfg, path)
    assert load(path.with_name("config.json.bak")).color == "#00FF66"
