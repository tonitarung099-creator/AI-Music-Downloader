import json
from pathlib import Path

import app.config as config_module
from app.config import AppConfig


def test_save_uses_relative_path_inside_portable_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "app_root", lambda: tmp_path)
    downloads = tmp_path / "downloads"
    cfg = AppConfig(output_dir=str(downloads))

    cfg.save()

    raw = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert raw["output_dir"] == "downloads"


def test_load_resolves_relative_path_against_current_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "app_root", lambda: tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps({"output_dir": "downloads", "audio_mode": "original"}),
        encoding="utf-8",
    )

    cfg = AppConfig.load()

    assert Path(cfg.output_dir) == (tmp_path / "downloads").resolve()


def test_external_output_path_stays_absolute(tmp_path, monkeypatch):
    portable_root = tmp_path / "portable"
    portable_root.mkdir()
    external = tmp_path / "music"
    monkeypatch.setattr(config_module, "app_root", lambda: portable_root)
    cfg = AppConfig(output_dir=str(external))

    cfg.save()

    raw = json.loads((portable_root / "config.json").read_text(encoding="utf-8"))
    assert Path(raw["output_dir"]) == external.resolve()
