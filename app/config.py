from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4


AUDIO_MODES = {"original", "m4a", "mp3"}
DEFAULT_AUDIO_MODE = "original"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_MAX_RETRIES = 2
MAX_RETRIES_LIMIT = 10


class ConfigSaveError(RuntimeError):
    pass


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_output_dir(value: str | None) -> str:
    """Resolve an output path consistently against the portable app root."""
    text = str(value or "").strip() or "downloads"
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = app_root() / path
    return str(path.resolve())


def _resolve_output_dir(value: str) -> str:
    """Backward-compatible alias kept for existing callers/tests."""
    return resolve_output_dir(value)


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


def _clean_api_keys(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= 100:
            break
    return result


def _valid_retries(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_MAX_RETRIES
    return max(0, min(MAX_RETRIES_LIMIT, value))


@dataclass
class AppConfig:
    output_dir: str = field(default_factory=lambda: str(app_root() / "downloads"))
    audio_mode: str = DEFAULT_AUDIO_MODE
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_api_keys: list[str] = field(default_factory=list)
    max_retries: int = DEFAULT_MAX_RETRIES

    @property
    def config_path(self) -> Path:
        return app_root() / "config.json"

    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        path = app_root() / "config.json"
        raw: dict[str, object] = {}

        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    raw = loaded
            except (OSError, json.JSONDecodeError, UnicodeError):
                raw = {}

        output_dir = raw.get("output_dir")
        if isinstance(output_dir, str) and output_dir.strip():
            cfg.output_dir = resolve_output_dir(output_dir)
        else:
            cfg.output_dir = resolve_output_dir("downloads")

        audio_mode = raw.get("audio_mode")
        if isinstance(audio_mode, str) and audio_mode in AUDIO_MODES:
            cfg.audio_mode = audio_mode

        gemini_model = raw.get("gemini_model")
        if isinstance(gemini_model, str) and gemini_model.strip():
            cfg.gemini_model = gemini_model.strip()

        cfg.max_retries = _valid_retries(raw.get("max_retries"))
        cfg.gemini_api_keys = _clean_api_keys(raw.get("gemini_api_keys"))

        env_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY")
        if env_keys:
            parsed = [x.strip() for x in env_keys.replace("\n", ",").split(",") if x.strip()]
            if parsed:
                cfg.gemini_api_keys = _clean_api_keys(parsed)
        return cfg

    def snapshot(self) -> "AppConfig":
        """Return a detached settings snapshot for a running batch."""
        return AppConfig(
            output_dir=resolve_output_dir(self.output_dir),
            audio_mode=self.audio_mode if self.audio_mode in AUDIO_MODES else DEFAULT_AUDIO_MODE,
            gemini_model=(self.gemini_model or DEFAULT_GEMINI_MODEL).strip(),
            gemini_api_keys=list(self.gemini_api_keys[:100]),
            max_retries=_valid_retries(self.max_retries),
        )

    def save(self) -> None:
        self.output_dir = resolve_output_dir(self.output_dir)
        if self.audio_mode not in AUDIO_MODES:
            self.audio_mode = DEFAULT_AUDIO_MODE
        self.gemini_model = (self.gemini_model or DEFAULT_GEMINI_MODEL).strip()
        self.max_retries = _valid_retries(self.max_retries)
        self.gemini_api_keys = _clean_api_keys(self.gemini_api_keys)

        data = asdict(self)
        data["output_dir"] = _serialize_output_dir(self.output_dir)
        data["gemini_api_keys"] = self.gemini_api_keys[:100]

        path = self.config_path
        backup = path.with_name(path.name + ".bak")
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                shutil.copy2(path, backup)

            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temp, path)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise ConfigSaveError(f"Gagal menyimpan config.json: {exc}") from exc
