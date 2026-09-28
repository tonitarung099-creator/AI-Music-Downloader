from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from PySide6.QtCore import QThread, Signal
from yt_dlp import YoutubeDL

from app.config import AppConfig
from app.models import TrackRequest, TrackStatus
from app.services.downloader import DownloadCancelled, DownloadEngine
from app.services.gemini_agent import GeminiAgent
from app.services.spotify import SpotifyResolverError, resolve_spotify


URL_RE = re.compile(r"^https?://", re.I)
SPOTIFY_HOSTS = {"open.spotify.com"}
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


@dataclass(slots=True)
class ImportIssue:
    line_number: int
    raw_input: str
    message: str


@dataclass(slots=True)
class ImportResult:
    import_id: str
    batch_id: str
    tracks: list[TrackRequest]
    issues: list[ImportIssue]
    cancelled: bool = False


def _parsed_http_url(url: str):
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if not parsed.hostname:
        return None
    return parsed


def _is_spotify(url: str) -> bool:
    parsed = _parsed_http_url(url)
    if parsed is None or parsed.hostname.lower() not in SPOTIFY_HOSTS:
        return False
    parts = [part for part in parsed.path.split("/") if part]
    return len(parts) >= 2 and parts[0].lower() in {"track", "album", "playlist"} and bool(parts[1])


def _is_youtube_playlist(url: str) -> bool:
    parsed = _parsed_http_url(url)
    if parsed is None or parsed.hostname.lower() not in YOUTUBE_HOSTS:
        return False
    query = parse_qs(parsed.query, keep_blank_values=False)
    list_values = [value for value in query.get("list", []) if str(value).strip()]
    if not list_values:
        return False
    if parsed.hostname.lower() == "youtu.be":
        return True
    return parsed.path.rstrip("/").lower() == "/playlist" or "list" in query


def _youtube_playlist_entries(url: str) -> list[dict]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": False,
        "socket_timeout": 15,
        "retries": 2,
        "extractor_retries": 1,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return list((info or {}).get("entries") or [])


class ImportWorker(QThread):
    tracks_ready = Signal(object)
    result_ready = Signal(object)
    log = Signal(str)
    failed = Signal(str)

    def __init__(self, raw_text: str, start_index: int = 1, parent=None) -> None:
        super().__init__(parent)
        self.raw_text = raw_text
        self.start_index = start_index
        self.import_id = uuid4().hex
        self.batch_id = uuid4().hex
        self.stop_event = threading.Event()

    def cancel(self) -> None:
        self.stop_event.set()
        self.requestInterruption()

    def _new_track(self, index: int, query: str, **kwargs) -> TrackRequest:
        return TrackRequest(index=index, query=query, batch_id=self.batch_id, **kwargs)

    def _import_line(self, line: str, index: int) -> tuple[list[TrackRequest], int]:
        tracks: list[TrackRequest] = []

        if _is_spotify(line):
            self.log.emit("Membaca metadata Spotify...")
            spotify_tracks = resolve_spotify(line, timeout=20)
            for item in spotify_tracks:
                if self.stop_event.is_set():
                    break
                tracks.append(self._new_track(
                    index=index,
                    query=item.query,
                    source="spotify",
                    title=item.title,
                    artist=item.artist,
                    duration=item.duration,
                ))
                index += 1
            return tracks, index

        if URL_RE.match(line) and _is_youtube_playlist(line):
            self.log.emit("Membaca playlist YouTube...")
            entries = _youtube_playlist_entries(line)
            for entry_pos, entry in enumerate(entries, start=1):
                if self.stop_event.is_set():
                    break
                if not isinstance(entry, dict):
                    self.failed.emit(f"Playlist YouTube: entri {entry_pos} kosong/tidak valid dan dilewati.")
                    continue

                video_id = entry.get("id")
                video_url = entry.get("url") or ""
                if video_url and not str(video_url).startswith("http") and video_id:
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                elif not video_url and video_id:
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                if not video_url:
                    self.failed.emit(f"Playlist YouTube: entri {entry_pos} tidak memiliki URL dan dilewati.")
                    continue

                title = entry.get("title") or f"Video {index}"
                tracks.append(self._new_track(
                    index=index,
                    query=str(title),
                    source="youtube_playlist",
                    direct_url=str(video_url),
                    title=str(title),
                    duration=entry.get("duration"),
                ))
                index += 1
            return tracks, index

        if URL_RE.match(line):
            parsed = _parsed_http_url(line)
            if parsed is None:
                raise ValueError("URL tidak valid.")
            host = parsed.hostname.lower()
            tracks.append(self._new_track(
                index=index,
                query=line,
                source=host or "url",
                direct_url=line,
            ))
            return tracks, index + 1

        clean = re.sub(r"^\s*\d+[.)\-:]\s*", "", line).strip()
        if clean:
            tracks.append(self._new_track(index=index, query=clean, source="manual"))
            return tracks, index + 1
        return tracks, index

    def run(self) -> None:
        tracks: list[TrackRequest] = []
        issues: list[ImportIssue] = []
        lines = [x.strip() for x in self.raw_text.splitlines() if x.strip()]
        index = self.start_index

        for line_number, line in enumerate(lines, start=1):
            if self.stop_event.is_set() or self.isInterruptionRequested():
                break
            try:
                new_tracks, index = self._import_line(line, index)
                tracks.extend(new_tracks)
            except SpotifyResolverError as exc:
                issue = ImportIssue(line_number, line, f"Spotify: {exc}")
                issues.append(issue)
                self.failed.emit(f"Baris {line_number}: {issue.message}")
            except Exception as exc:
                issue = ImportIssue(line_number, line, str(exc) or "Input gagal diproses.")
                issues.append(issue)
                self.failed.emit(f"Baris {line_number}: {issue.message}")

        cancelled = self.stop_event.is_set() or self.isInterruptionRequested()
        result = ImportResult(
            import_id=self.import_id,
            batch_id=self.batch_id,
            tracks=tracks,
            issues=issues,
            cancelled=cancelled,
        )
        self.tracks_ready.emit(tracks)
        self.result_ready.emit(result)


class QueueWorker(QThread):
    item_changed = Signal(str, str, float, str)
    log = Signal(str)
    finished_summary = Signal(int, int, int)

    def __init__(self, tracks: list[TrackRequest], config: AppConfig, gemini: GeminiAgent, parent=None) -> None:
        super().__init__(parent)
        self.tracks = list(tracks)
        self.config = config.snapshot()
        self.gemini = gemini
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.engine = DownloadEngine(gemini)

    def pause(self) -> None:
        self.pause_event.set()
        self.log.emit("Download dijeda.")

    def resume(self) -> None:
        self.pause_event.clear()
        self.log.emit("Download dilanjutkan.")

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()
        self.requestInterruption()
        self.log.emit("Menghentikan antrean...")

    def _wait_while_paused(self) -> None:
        while self.pause_event.is_set() and not self.stop_event.is_set():
            self.stop_event.wait(0.2)

    def run(self) -> None:
        done = failed = cancelled = 0
        for track in self.tracks:
            if track.status == TrackStatus.DONE:
                continue

            if self.stop_event.is_set() or self.isInterruptionRequested():
                track.status = TrackStatus.CANCELLED
                self.item_changed.emit(track.job_id, track.status.value, track.progress, "Dibatalkan")
                cancelled += 1
                continue

            self._wait_while_paused()
            if self.stop_event.is_set() or self.isInterruptionRequested():
                track.status = TrackStatus.CANCELLED
                self.item_changed.emit(track.job_id, track.status.value, track.progress, "Dibatalkan")
                cancelled += 1
                continue

            attempts = max(1, int(self.config.max_retries) + 1)
            last_error = ""
            success = False
            for attempt in range(attempts):
                if self.stop_event.is_set() or self.isInterruptionRequested():
                    break
                self._wait_while_paused()

                try:
                    def progress(pct: float, detail: str) -> None:
                        track.progress = pct
                        status = TrackStatus.PAUSED.value if self.pause_event.is_set() else track.status.value
                        self.item_changed.emit(track.job_id, status, pct, detail)

                    track.status = TrackStatus.SEARCHING
                    self.item_changed.emit(track.job_id, track.status.value, 0.0, "Menyiapkan...")
                    self.engine.download(
                        track,
                        output_dir=self.config.output_dir,
                        audio_mode=self.config.audio_mode,
                        progress_cb=progress,
                        pause_event=self.pause_event,
                        stop_event=self.stop_event,
                    )
                    track.status = TrackStatus.DONE
                    track.progress = 100.0
                    self.item_changed.emit(track.job_id, track.status.value, 100.0, track.resolved_title or "Selesai")
                    done += 1
                    success = True
                    break
                except DownloadCancelled:
                    track.status = TrackStatus.CANCELLED
                    self.item_changed.emit(track.job_id, track.status.value, track.progress, "Dibatalkan")
                    cancelled += 1
                    break
                except Exception as exc:
                    if self.stop_event.is_set() or self.isInterruptionRequested():
                        track.status = TrackStatus.CANCELLED
                        self.item_changed.emit(track.job_id, track.status.value, track.progress, "Dibatalkan")
                        cancelled += 1
                        break
                    last_error = str(exc)
                    if attempt + 1 < attempts:
                        self.item_changed.emit(
                            track.job_id,
                            "Mencoba lagi",
                            track.progress,
                            f"Retry {attempt + 1}/{attempts - 1}",
                        )
                        continue

            if not success and track.status != TrackStatus.CANCELLED:
                track.status = TrackStatus.FAILED
                track.error = last_error
                self.item_changed.emit(track.job_id, track.status.value, track.progress, last_error[-180:])
                failed += 1

        self.finished_summary.emit(done, failed, cancelled)
