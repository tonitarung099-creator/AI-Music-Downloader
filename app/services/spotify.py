from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from spotdl.types.album import Album
from spotdl.types.playlist import Playlist
from spotdl.types.song import Song


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
    """Compatibility parser kept for old saved spotDL output and tests."""
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
        if duration_f and duration_f > 10_000:
            duration_f /= 1000.0
    except (TypeError, ValueError):
        duration_f = None

    if not title:
        return None
    return SpotifyTrack(title=title, artist=artist, duration=duration_f)


def _song_to_track(song: Song) -> SpotifyTrack:
    artists = getattr(song, "artists", None) or []
    artist = ", ".join(str(x).strip() for x in artists if str(x).strip())
    if not artist:
        artist = str(getattr(song, "artist", "") or "").strip()

    duration_raw = getattr(song, "duration", None)
    try:
        duration = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration = None

    return SpotifyTrack(
        title=str(getattr(song, "name", "") or "").strip(),
        artist=artist,
        duration=duration,
    )


def resolve_spotify(url: str, timeout: int = 120) -> list[SpotifyTrack]:
    """Resolve Spotify metadata in-process.

    This intentionally does not download Spotify audio or bypass DRM. spotDL's
    Spotify metadata layer is used only to obtain artist/title/duration, after
    which the normal matcher searches a supported audio source.

    Running in-process is important for the portable Windows build: when the
    application is frozen, ``sys.executable`` points at our EXE rather than a
    Python interpreter, so ``python -m spotdl`` would not work.
    """
    del timeout  # kept for API compatibility with the previous subprocess version
    normalized = (url or "").strip()
    if not normalized:
        raise SpotifyResolverError("URL Spotify kosong.")

    try:
        if "/playlist/" in normalized:
            _, songs = Playlist.get_metadata(normalized)
        elif "/album/" in normalized:
            _, songs = Album.get_metadata(normalized)
        elif "/track/" in normalized:
            songs = [Song.from_url(normalized)]
        else:
            raise SpotifyResolverError(
                "Jenis URL Spotify belum didukung. Gunakan link track, album, atau playlist."
            )
    except SpotifyResolverError:
        raise
    except Exception as exc:
        raise SpotifyResolverError(f"Gagal membaca metadata Spotify: {exc}") from exc

    tracks = [_song_to_track(song) for song in songs]
    result = [track for track in tracks if track.title]
    if not result:
        raise SpotifyResolverError("Tidak ada lagu Spotify yang berhasil dibaca.")
    return result
