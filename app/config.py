from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass
class AppConfig:
    output_dir: str = str(app_root() / "downloads")
    audio_mode: str = "original"
    gemini_model: str = "gemini-2.5-flash"
    gemini_api_keys: list[str] = field(default_factory=list)
    max_retries: int = 2

    @property
    def config_path(self) -> Path:
        return app_root() / "config.json"

    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        path = app_root() / "config.json"
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                for key in ("output_dir", "audio_mode", "gemini_model", "max_retries"):
                    if key in raw:
                        setattr(cfg, key, raw[key])
                if isinstance(raw.get("gemini_api_keys"), list):
                    cfg.gemini_api_keys = [str(x).strip() for x in raw["gemini_api_keys"] if str(x).strip()]
            except (OSError, json.JSONDecodeError):
                pass

        env_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY")
        if env_keys:
            parsed = [x.strip() for x in env_keys.replace("\n", ",").split(",") if x.strip()]
            if parsed:
                cfg.gemini_api_keys = parsed[:100]
        return cfg

    def save(self) -> None:
        data = asdict(self)
        data["gemini_api_keys"] = self.gemini_api_keys[:100]
        self.config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
