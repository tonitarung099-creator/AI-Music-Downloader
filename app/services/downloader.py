from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Callable

from yt_dlp import YoutubeDL

from app.config import app_root
from app.models import TrackRequest, TrackStatus
from app.services.gemini_agent import GeminiAgent
from app.services.matcher import Candidate, is_ambiguous, search_youtube


ProgressCallback = Callable[[float, str], None]


class DownloadCancelled(RuntimeError):
    pass


class DownloadEngine:
    def __init__(self, gemini: GeminiAgent | None = None) -> None:
        self.gemini = gemini

    @staticmethod
    def ffmpeg_location() -> str | None:
        portable = app_root() / "tools" / "ffmpeg.exe"
        if portable.exists():
            return str(portable.parent)
        system = shutil.which("ffmpeg")
        return str(Path(system).parent) if system else None

    def resolve_candidate(
        self,
        track: TrackRequest,
        stop_event: threading.Event | None = None,
    ) -> Candidate:
        if stop_event and stop_event.is_set():
            raise DownloadCancelled("Dibatalkan pengguna.")

        ranked = search_youtube(track.query, limit=8, expected_duration=track.duration)
        if stop_event and stop_event.is_set():
            raise DownloadCancelled("Dibatalkan pengguna.")
        if not ranked:
            raise RuntimeError("Tidak menemukan kandidat YouTube.")

        chosen = ranked[0]
        if is_ambiguous(ranked) and self.gemini and self.gemini.available:
            idx = self.gemini.choose_candidate(track.query, ranked, cancel_event=stop_event)
            if stop_event and stop_event.is_set():
                raise DownloadCancelled("Dibatalkan pengguna.")
            if idx is not None:
                chosen = ranked[idx]
        return chosen

    @staticmethod
    def _best_effort_output_path(info: dict, ydl: YoutubeDL, audio_mode: str) -> str | None:
        candidates: list[Path] = []
        requested = info.get("requested_downloads") or []
        if isinstance(requested, list):
            for item in requested:
                if isinstance(item, dict) and item.get("filepath"):
                    candidates.append(Path(str(item["filepath"])))
        for key in ("filepath", "_filename"):
            value = info.get(key)
            if value:
                candidates.append(Path(str(value)))
        try:
            candidates.append(Path(ydl.prepare_filename(info)))
        except Exception:
            pass

        expanded: list[Path] = []
        for candidate in candidates:
            expanded.append(candidate)
            if audio_mode == "mp3":
                expanded.append(candidate.with_suffix(".mp3"))

        for candidate in expanded:
            try:
                if candidate.exists() and candidate.is_file():
                    return str(candidate.resolve())
            except OSError:
                continue
        return None

    def download(
        self,
        track: TrackRequest,
        output_dir: str,
        audio_mode: str,
        progress_cb: ProgressCallback | None = None,
        pause_event: threading.Event | None = None,
        stop_event: threading.Event | None = None,
    ) -> dict:
        if stop_event and stop_event.is_set():
            raise DownloadCancelled("Dibatalkan pengguna.")

        if track.direct_url:
            url = track.direct_url
        elif track.resolved_url:
            url = track.resolved_url
            if progress_cb:
                progress_cb(0.0, "Menggunakan kandidat yang sudah dipilih sebelumnya...")
        else:
            track.status = TrackStatus.SEARCHING
            if progress_cb:
                progress_cb(0.0, "Mencari versi terbaik...")
            candidate = self.resolve_candidate(track, stop_event=stop_event)
            track.resolved_url = candidate.url
            track.resolved_title = candidate.title
            track.metadata["match_score"] = candidate.score
            track.metadata["matched_channel"] = candidate.uploader
            url = candidate.url

        if stop_event and stop_event.is_set():
            raise DownloadCancelled("Dibatalkan pengguna.")

        destination = Path(output_dir).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)

        def hook(data: dict) -> None:
            if stop_event and stop_event.is_set():
                raise DownloadCancelled("Dibatalkan pengguna.")
            if pause_event:
                while pause_event.is_set():
                    if stop_event and stop_event.is_set():
                        raise DownloadCancelled("Dibatalkan pengguna.")
                    stop_event.wait(0.2) if stop_event else threading.Event().wait(0.2)

            if not progress_cb:
                return
            status = data.get("status")
            if status == "downloading":
                downloaded = float(data.get("downloaded_bytes") or 0)
                total = float(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
                pct = (downloaded / total * 100.0) if total > 0 else 0.0
                speed = data.get("_speed_str") or ""
                eta = data.get("_eta_str") or ""
                detail = " ".join(x for x in (speed, f"ETA {eta}" if eta else "") if x).strip()
                progress_cb(pct, detail or "Mengunduh...")
            elif status == "finished":
                progress_cb(100.0, "Download selesai, memproses file...")

        # File identity must not depend on queue order. yt-dlp media ID keeps the
        # filename stable even when rows are reordered between sessions.
        opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": str(destination / "%(title).160B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "windowsfilenames": True,
            "overwrites": False,
            "continuedl": True,
            # Retry ownership lives in QueueWorker so one failure does not create
            # nested retry storms inside yt-dlp and the queue scheduler.
            "retries": 0,
            "fragment_retries": 0,
            "extractor_retries": 1,
            "socket_timeout": 15,
            "progress_hooks": [hook],
        }

        ffmpeg = self.ffmpeg_location()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg

        if audio_mode == "m4a":
            opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
        elif audio_mode == "mp3":
            if not ffmpeg:
                raise RuntimeError("Mode MP3 membutuhkan FFmpeg. Letakkan FFmpeg di tools/ atau PATH.")
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }]

        track.status = TrackStatus.DOWNLOADING
        if progress_cb:
            progress_cb(0.0, "Memulai download...")

        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
            if info:
                track.output_path = self._best_effort_output_path(info, ydl, audio_mode)

        if stop_event and stop_event.is_set():
            raise DownloadCancelled("Dibatalkan pengguna.")

        if info.get("id"):
            track.metadata["source_media_id"] = str(info["id"])
        if info.get("extractor_key"):
            track.metadata["source_extractor"] = str(info["extractor_key"])
        return info
