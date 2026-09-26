from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SpotifyTrack:
    title: str
    artist: str
    duration: float | None = None

    @property
    def query(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title


class SpotifyResolverError(RuntimeError):
    pass


def _extract_json_payload(stdout: str) -> Any:
    text = (stdout or "").strip()
    if not text:
        raise SpotifyResolverError("spotDL tidak mengembalikan metadata.")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        starts = [pos for pos in (text.find("["), text.find("{")) if pos >= 0]
        if not starts:
            raise SpotifyResolverError("Metadata Spotify tidak dapat dibaca.")
        start = min(starts)
        end = max(text.rfind("]"), text.rfind("}"))
        if end < start:
            raise SpotifyResolverError("Metadata Spotify tidak lengkap.")
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise SpotifyResolverError("Format metadata spotDL berubah/tidak dikenali.") from exc


def _to_track(item: dict[str, Any]) -> SpotifyTrack | None:
    title = str(item.get("name") or item.get("title") or "").strip()
    artists_raw = item.get("artists") or item.get("artist") or []
    if isinstance(artists_raw, list):
        artist = ", ".join(str(x).strip() for x in artists_raw if str(x).strip())
    else:
        artist = str(artists_raw).strip()

    duration = item.get("duration")
    try:
        duration_f = float(duration) if duration is not None else None
        if duration_f and duration_f > 10_000:  # milliseconds in some payloads
            duration_f /= 1000.0
    except (TypeError, ValueError):
        duration_f = None

    if not title:
        return None
    return SpotifyTrack(title=title, artist=artist, duration=duration_f)


def resolve_spotify(url: str, timeout: int = 120) -> list[SpotifyTrack]:
    """Resolve Spotify metadata with spotDL. No Spotify audio/DRM is accessed."""
    cmd = [sys.executable, "-m", "spotdl", "save", url, "--save-file", "-"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SpotifyResolverError(f"Gagal menjalankan spotDL: {exc}") from exc

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "spotDL gagal").strip()
        raise SpotifyResolverError(message[-700:])

    payload = _extract_json_payload(proc.stdout)
    if isinstance(payload, dict):
        items = payload.get("songs") or payload.get("tracks") or [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    tracks = [_to_track(x) for x in items if isinstance(x, dict)]
    result = [x for x in tracks if x is not None]
    if not result:
        raise SpotifyResolverError("Tidak ada lagu Spotify yang berhasil dibaca.")
    return result
