from __future__ import annotations

import json
import platform
import re
import sys
import zipfile
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4


_SECRET_NAME_RE = re.compile(r"(?:api[_-]?key|token|cookie|secret|authorization|password)", re.I)
_GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]{12,}")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:key|api_key|apikey|token|access_token|auth|authorization)=)([^&#\s]+)"
)
_GENERIC_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|cookie|secret|authorization)\s*[:=]\s*([^\s,;]+)"
)


def redact_text(value: object) -> str:
    text = str(value or "")
    text = _GOOGLE_KEY_RE.sub("<rahasia>", text)
    text = _BEARER_RE.sub("Bearer <rahasia>", text)
    text = _QUERY_SECRET_RE.sub(lambda match: f"{match.group(1)}<rahasia>", text)
    text = _GENERIC_SECRET_RE.sub(lambda match: f"{match.group(1)}=<rahasia>", text)
    return text


def sanitize_mapping(value: object) -> object:
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _SECRET_NAME_RE.search(key):
                cleaned[key] = "<rahasia>"
            else:
                cleaned[key] = sanitize_mapping(raw_value)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [sanitize_mapping(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


@dataclass(slots=True)
class LogEntry:
    created_at: str
    level: str
    message: str


class DiagnosticLog:
    def __init__(self, max_entries: int = 1000) -> None:
        self._entries: deque[LogEntry] = deque(maxlen=max(100, int(max_entries)))

    def append(self, message: object, level: str = "INFO") -> str:
        cleaned = redact_text(message)
        self._entries.append(
            LogEntry(
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                level=str(level or "INFO").upper()[:16],
                message=cleaned,
            )
        )
        return cleaned

    def entries(self) -> list[dict[str, str]]:
        return [asdict(entry) for entry in self._entries]

    def text(self) -> str:
        return "\n".join(
            f"{entry.created_at} [{entry.level}] {entry.message}" for entry in self._entries
        )


def diagnostic_payload(
    *,
    log: DiagnosticLog,
    config: object,
    tracks: Iterable[object],
    tool_status: object = None,
) -> dict[str, object]:
    safe_tracks: list[dict[str, object]] = []
    for track in tracks:
        metadata = sanitize_mapping(getattr(track, "metadata", {}) or {})
        safe_tracks.append(
            {
                "job_id": str(getattr(track, "job_id", "")),
                "status": str(getattr(getattr(track, "status", None), "value", "")),
                "source": str(getattr(track, "source", "")),
                "query": redact_text(getattr(track, "query", "")),
                "display_name": redact_text(getattr(track, "display_name", "")),
                "error_code": str(getattr(track, "error_code", "")),
                "error": redact_text(getattr(track, "error", "")),
                "metadata": metadata,
            }
        )

    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "config": {
            "audio_mode": str(getattr(config, "audio_mode", "")),
            "gemini_model": str(getattr(config, "gemini_model", "")),
            "gemini_key_storage": str(getattr(config, "gemini_key_storage", "")),
            "gemini_key_count": len(list(getattr(config, "gemini_api_keys", []) or [])),
            "max_retries": int(getattr(config, "max_retries", 0) or 0),
            "output_dir": redact_text(getattr(config, "output_dir", "")),
        },
        "tools": sanitize_mapping(tool_status or {}),
        "tracks": safe_tracks,
        "logs": log.entries(),
    }


def write_diagnostic_bundle(
    destination: str | Path,
    *,
    log: DiagnosticLog,
    config: object,
    tracks: Iterable[object],
    tool_status: object = None,
) -> Path:
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    payload = diagnostic_payload(log=log, config=config, tracks=tracks, tool_status=tool_status)
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "diagnostics.json",
                json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            )
            archive.writestr("log.txt", log.text() + ("\n" if log.text() else ""))
        temp.replace(target)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target
