from __future__ import annotations

import json
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(slots=True)
class SpotifyTrack:
    title: str
    artist: str
    duration: float | None = None

    @property
    def query(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title


@dataclass(frozen=True, slots=True)
class _SpotdlBackend:
    Album: Any
    Playlist: Any
    Song: Any
    SpotifyClient: Any
    SpotifyError: type[Exception]
    default_config: dict[str, Any]


class SpotifyResolverError(RuntimeError):
    pass


_backend_lock = threading.Lock()


def _load_spotdl_backend() -> _SpotdlBackend:
    """Import spotDL only when a Spotify URL is actually used."""
    try:
        from spotdl.types.album import Album
        from spotdl.types.playlist import Playlist
        from spotdl.types.song import Song
        from spotdl.utils.config import DEFAULT_CONFIG
        from spotdl.utils.spotify import SpotifyClient, SpotifyError
    except Exception as exc:
        raise SpotifyResolverError(
            "Komponen Spotify tidak tersedia. Input manual/YouTube tetap dapat digunakan."
        ) from exc

    return _SpotdlBackend(
        Album=Album,
        Playlist=Playlist,
        Song=Song,
        SpotifyClient=SpotifyClient,
        SpotifyError=SpotifyError,
        default_config=dict(DEFAULT_CONFIG),
    )


def _ensure_spotify_client(backend: _SpotdlBackend) -> None:
    """Initialize spotDL's selected Spotify backend exactly once per process."""
    with _backend_lock:
        try:
            backend.SpotifyClient()
            return
        except Exception:
            pass

        defaults = backend.default_config
        try:
            backend.SpotifyClient.init(
                client_id=str(defaults.get("client_id") or ""),
                client_secret=str(defaults.get("client_secret") or ""),
                user_auth=False,
                no_cache=bool(defaults.get("no_cache", False)),
                headless=True,
                max_retries=int(defaults.get("max_retries", 3) or 3),
                use_cache_file=False,
                use_official_api=False,
                auth_token=None,
                cache_path=defaults.get("cache_path"),
            )
        except Exception as exc:
            # A concurrent caller or another spotDL component may have initialized
            # the singleton between the probe and init call. Re-probe before failing.
            try:
                backend.SpotifyClient()
                return
            except Exception:
                raise SpotifyResolverError(
                    f"Gagal menyiapkan akses metadata Spotify: {exc}"
                ) from exc


@contextmanager
def _socket_deadline(timeout: int | float | None) -> Iterator[None]:
    """Best-effort socket deadline for spotDL backends that omit explicit timeout."""
    if timeout is None or timeout <= 0:
        yield
        return

    with _backend_lock:
        previous = socket.getdefaulttimeout()
        socket.setdefaulttimeout(float(timeout))
        try:
            yield
        finally:
            socket.setdefaulttimeout(previous)


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


def _song_to_track(song: Any) -> SpotifyTrack:
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


def resolve_spotify(url: str, timeout: int = 20) -> list[SpotifyTrack]:
    """Resolve Spotify metadata without making Spotify a mandatory app dependency."""
    normalized = (url or "").strip()
    if not normalized:
        raise SpotifyResolverError("URL Spotify kosong.")

    backend = _load_spotdl_backend()
    _ensure_spotify_client(backend)

    try:
        with _socket_deadline(timeout):
            if "/playlist/" in normalized:
                _, songs = backend.Playlist.get_metadata(normalized)
            elif "/album/" in normalized:
                _, songs = backend.Album.get_metadata(normalized)
            elif "/track/" in normalized:
                songs = [backend.Song.from_url(normalized)]
            else:
                raise SpotifyResolverError(
                    "Jenis URL Spotify belum didukung. Gunakan link track, album, atau playlist."
                )
    except SpotifyResolverError:
        raise
    except Exception as exc:
        raise SpotifyResolverError(f"Gagal membaca metadata Spotify: {exc}") from exc

    tracks = [_song_to_track(song) for song in songs if song is not None]
    result = [track for track in tracks if track.title]
    if not result:
        raise SpotifyResolverError("Tidak ada lagu Spotify yang berhasil dibaca.")
    return result
