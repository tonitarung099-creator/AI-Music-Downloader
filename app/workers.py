from __future__ import annotations

import re
import threading
from urllib.parse import urlparse

from PySide6.QtCore import QThread, Signal
from yt_dlp import YoutubeDL

from app.config import AppConfig
from app.models import TrackRequest, TrackStatus
from app.services.downloader import DownloadCancelled, DownloadEngine
from app.services.gemini_agent import GeminiAgent
from app.services.spotify import SpotifyResolverError, resolve_spotify


URL_RE = re.compile(r"^https?://", re.I)


def _is_spotify(url: str) -> bool:
    return "open.spotify.com/" in url.lower()


def _is_youtube_playlist(url: str) -> bool:
    low = url.lower()
    return ("youtube.com/playlist" in low) or ("youtube.com/" in low and "list=" in low)


def _youtube_playlist_entries(url: str) -> list[dict]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": False,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return list((info or {}).get("entries") or [])


class ImportWorker(QThread):
    tracks_ready = Signal(object)
    log = Signal(str)
    failed = Signal(str)

    def __init__(self, raw_text: str, start_index: int = 1, parent=None) -> None:
        super().__init__(parent)
        self.raw_text = raw_text
        self.start_index = start_index

    def run(self) -> None:
        try:
            tracks: list[TrackRequest] = []
            lines = [x.strip() for x in self.raw_text.splitlines() if x.strip()]
            index = self.start_index

            for line in lines:
                if _is_spotify(line):
                    self.log.emit("Membaca metadata Spotify...")
                    spotify_tracks = resolve_spotify(line)
                    for item in spotify_tracks:
                        tracks.append(TrackRequest(
                            index=index,
                            query=item.query,
                            source="spotify",
                            title=item.title,
                            artist=item.artist,
                            duration=item.duration,
                        ))
                        index += 1
                    continue

                if URL_RE.match(line) and _is_youtube_playlist(line):
                    self.log.emit("Membaca playlist YouTube...")
                    entries = _youtube_playlist_entries(line)
                    for entry in entries:
                        video_id = entry.get("id")
                        video_url = entry.get("url") or ""
                        if video_url and not str(video_url).startswith("http") and video_id:
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                        elif not video_url and video_id:
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                        title = entry.get("title") or f"Video {index}"
                        tracks.append(TrackRequest(
                            index=index,
                            query=title,
                            source="youtube_playlist",
                            direct_url=str(video_url),
                            title=title,
                            duration=entry.get("duration"),
                        ))
                        index += 1
                    continue

                if URL_RE.match(line):
                    host = urlparse(line).netloc.lower()
                    tracks.append(TrackRequest(
                        index=index,
                        query=line,
                        source=host or "url",
                        direct_url=line,
                    ))
                    index += 1
                    continue

                clean = re.sub(r"^\s*\d+[.)\-:]\s*", "", line).strip()
                if clean:
                    tracks.append(TrackRequest(index=index, query=clean, source="manual"))
                    index += 1

            self.tracks_ready.emit(tracks)
        except SpotifyResolverError as exc:
            self.failed.emit(f"Spotify: {exc}")
        except Exception as exc:
            self.failed.emit(str(exc))


class QueueWorker(QThread):
    item_changed = Signal(int, str, float, str)
    log = Signal(str)
    finished_summary = Signal(int, int, int)

    def __init__(self, tracks: list[TrackRequest], config: AppConfig, gemini: GeminiAgent, parent=None) -> None:
        super().__init__(parent)
        self.tracks = tracks
        self.config = config
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
        self.log.emit("Menghentikan antrean...")

    def _wait_while_paused(self) -> None:
        while self.pause_event.is_set() and not self.stop_event.is_set():
            self.stop_event.wait(0.2)

    def run(self) -> None:
        done = failed = cancelled = 0
        for row, track in enumerate(self.tracks):
            if track.status == TrackStatus.DONE:
                continue

            if self.stop_event.is_set():
                track.status = TrackStatus.CANCELLED
                self.item_changed.emit(row, track.status.value, track.progress, "Dibatalkan")
                cancelled += 1
                continue

            self._wait_while_paused()
            if self.stop_event.is_set():
                track.status = TrackStatus.CANCELLED
                self.item_changed.emit(row, track.status.value, track.progress, "Dibatalkan")
                cancelled += 1
                continue

            attempts = max(1, int(self.config.max_retries) + 1)
            last_error = ""
            success = False
            for attempt in range(attempts):
                if self.stop_event.is_set():
                    break
                self._wait_while_paused()

                try:
                    def progress(pct: float, detail: str, r=row) -> None:
                        track.progress = pct
                        status = TrackStatus.PAUSED.value if self.pause_event.is_set() else track.status.value
                        self.item_changed.emit(r, status, pct, detail)

                    track.status = TrackStatus.SEARCHING
                    self.item_changed.emit(row, track.status.value, 0.0, "Menyiapkan...")
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
                    self.item_changed.emit(row, track.status.value, 100.0, track.resolved_title or "Selesai")
                    done += 1
                    success = True
                    break
                except DownloadCancelled:
                    track.status = TrackStatus.CANCELLED
                    self.item_changed.emit(row, track.status.value, track.progress, "Dibatalkan")
                    cancelled += 1
                    break
                except Exception as exc:
                    if self.stop_event.is_set():
                        track.status = TrackStatus.CANCELLED
                        self.item_changed.emit(row, track.status.value, track.progress, "Dibatalkan")
                        cancelled += 1
                        break
                    last_error = str(exc)
                    if attempt + 1 < attempts:
                        self.item_changed.emit(row, "Mencoba lagi", track.progress, f"Retry {attempt + 1}/{attempts - 1}")
                        continue

            if not success and track.status != TrackStatus.CANCELLED:
                track.status = TrackStatus.FAILED
                track.error = last_error
                self.item_changed.emit(row, track.status.value, track.progress, last_error[-180:])
                failed += 1

        self.finished_summary.emit(done, failed, cancelled)
