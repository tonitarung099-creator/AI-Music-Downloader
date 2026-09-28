from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from app.services.secure_keys import SecureKeyStoreError, WindowsDpapiKeyStore


AUDIO_MODES = {"original", "m4a", "mp3"}
DEFAULT_AUDIO_MODE = "original"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_MAX_RETRIES = 2
MAX_RETRIES_LIMIT = 10
KEY_STORAGE_MODES = {"windows_dpapi", "session"}


class ConfigSaveError(RuntimeError):
    pass


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_output_dir(value: object = None) -> str:
    """Resolve an output path consistently against the portable app root."""
    text = value.strip() if isinstance(value, str) else ""
    text = text or "downloads"
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = app_root() / path
    return str(path.resolve())


def _resolve_output_dir(value: str) -> str:
    """Backward-compatible alias kept for existing callers/tests."""
    return resolve_output_dir(value)


def _serialize_output_dir(value: object) -> str:
    """Store paths inside the portable folder relatively so moves keep working."""
    root = app_root().resolve()
    text = value.strip() if isinstance(value, str) else ""
    path = Path(text or "downloads").expanduser()
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


def _valid_audio_mode(value: object) -> str:
    return value if isinstance(value, str) and value in AUDIO_MODES else DEFAULT_AUDIO_MODE


def _valid_model(value: object) -> str:
    if not isinstance(value, str):
        return DEFAULT_GEMINI_MODEL
    text = value.strip()
    return text or DEFAULT_GEMINI_MODEL


def _valid_retries(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_MAX_RETRIES
    return max(0, min(MAX_RETRIES_LIMIT, value))


def _default_key_storage() -> str:
    return "windows_dpapi" if os.name == "nt" else "session"


def _valid_key_storage(value: object) -> str:
    return value if isinstance(value, str) and value in KEY_STORAGE_MODES else _default_key_storage()


@dataclass
class AppConfig:
    output_dir: str = field(default_factory=lambda: str(app_root() / "downloads"))
    audio_mode: str = DEFAULT_AUDIO_MODE
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_api_keys: list[str] = field(default_factory=list)
    gemini_key_storage: str = field(default_factory=_default_key_storage)
    max_retries: int = DEFAULT_MAX_RETRIES
    key_storage_warning: str = field(default="", init=False, repr=False, compare=False)

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

        cfg.output_dir = resolve_output_dir(raw.get("output_dir"))
        cfg.audio_mode = _valid_audio_mode(raw.get("audio_mode"))
        cfg.gemini_model = _valid_model(raw.get("gemini_model"))
        cfg.max_retries = _valid_retries(raw.get("max_retries"))
        cfg.gemini_key_storage = _valid_key_storage(raw.get("gemini_key_storage"))
        legacy_keys = _clean_api_keys(raw.get("gemini_api_keys"))
        cfg.gemini_api_keys = legacy_keys

        if cfg.gemini_key_storage == "windows_dpapi":
            store = WindowsDpapiKeyStore(app_root())
            if store.available:
                try:
                    secure_keys = store.load()
                except SecureKeyStoreError as exc:
                    cfg.key_storage_warning = str(exc)
                else:
                    if secure_keys:
                        cfg.gemini_api_keys = secure_keys
            elif not legacy_keys:
                cfg.key_storage_warning = (
                    "Penyimpanan aman Windows tidak tersedia; API key perlu dimasukkan untuk sesi ini."
                )

        env_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY")
        if env_keys:
            parsed = [x.strip() for x in env_keys.replace("\n", ",").split(",") if x.strip()]
            if parsed:
                cfg.gemini_api_keys = _clean_api_keys(parsed)
                cfg.gemini_key_storage = "session"
        return cfg

    def snapshot(self) -> "AppConfig":
        """Return a detached settings snapshot for a running batch."""
        snapshot = AppConfig(
            output_dir=resolve_output_dir(self.output_dir),
            audio_mode=_valid_audio_mode(self.audio_mode),
            gemini_model=_valid_model(self.gemini_model),
            gemini_api_keys=_clean_api_keys(self.gemini_api_keys),
            gemini_key_storage=_valid_key_storage(self.gemini_key_storage),
            max_retries=_valid_retries(self.max_retries),
        )
        return snapshot

    def save(self) -> None:
        self.output_dir = resolve_output_dir(self.output_dir)
        self.audio_mode = _valid_audio_mode(self.audio_mode)
        self.gemini_model = _valid_model(self.gemini_model)
        self.max_retries = _valid_retries(self.max_retries)
        self.gemini_api_keys = _clean_api_keys(self.gemini_api_keys)
        self.gemini_key_storage = _valid_key_storage(self.gemini_key_storage)

        data = asdict(self)
        data.pop("key_storage_warning", None)
        data["output_dir"] = _serialize_output_dir(self.output_dir)
        data["gemini_api_keys"] = []

        store = WindowsDpapiKeyStore(app_root())
        remove_secure_after_save = False
        if self.gemini_key_storage == "windows_dpapi":
            if not store.available:
                raise ConfigSaveError(
                    "Penyimpanan Windows DPAPI tidak tersedia. Pilih mode 'hanya sesi ini' untuk API key."
                )
            try:
                store.save(self.gemini_api_keys)
            except SecureKeyStoreError as exc:
                raise ConfigSaveError(str(exc)) from exc
        else:
            remove_secure_after_save = store.available

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

        if remove_secure_after_save:
            try:
                store.delete()
            except SecureKeyStoreError:
                # Mode sesi sudah tersimpan di config; blob lama tidak akan dibaca lagi.
                pass
        self.key_storage_warning = ""
