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


def _resolve_output_dir(value: str) -> str:
    """Resolve a saved relative output path against the current app folder."""
    path = Path(value or "downloads").expanduser()
    if not path.is_absolute():
        path = app_root() / path
    return str(path.resolve())


def _serialize_output_dir(value: str) -> str:
    """Store paths inside the portable folder relatively so moves keep working."""
    root = app_root().resolve()
    path = Path(value or "downloads").expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return str(path)
    return relative.as_posix() or "."


@dataclass
class AppConfig:
    output_dir: str = str(app_root() / "downloads")
    audio_mode: str = "original"
    gemini_model: str = "gemini-3.8-flash"
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
                if "output_dir" in raw:
                    cfg.output_dir = _resolve_output_dir(str(raw["output_dir"]))
                for key in ("audio_mode", "gemini_model", "max_retries"):
                    if key in raw:
                        setattr(cfg, key, raw[key])
                if isinstance(raw.get("gemini_api_keys"), list):
                    cfg.gemini_api_keys = [str(x).strip() for x in raw["gemini_api_keys"] if str(x).strip()][:100]
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
        data["output_dir"] = _serialize_output_dir(self.output_dir)
        data["gemini_api_keys"] = self.gemini_api_keys[:100]
        self.config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
