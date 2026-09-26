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

    def resolve_candidate(self, track: TrackRequest) -> Candidate:
        ranked = search_youtube(track.query, limit=8, expected_duration=track.duration)
        if not ranked:
            raise RuntimeError("Tidak menemukan kandidat YouTube.")

        chosen = ranked[0]
        if is_ambiguous(ranked) and self.gemini and self.gemini.available:
            idx = self.gemini.choose_candidate(track.query, ranked)
            if idx is not None:
                chosen = ranked[idx]
        return chosen

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
        else:
            track.status = TrackStatus.SEARCHING
            if progress_cb:
                progress_cb(0.0, "Mencari versi terbaik...")
            candidate = self.resolve_candidate(track)
            track.resolved_url = candidate.url
            track.resolved_title = candidate.title
            track.metadata["match_score"] = candidate.score
            track.metadata["matched_channel"] = candidate.uploader
            url = candidate.url

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

        prefix = f"{track.index:03d} - "
        opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": str(destination / f"{prefix}%(title).160B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "windowsfilenames": True,
            "overwrites": False,
            "continuedl": True,
            "retries": 5,
            "fragment_retries": 5,
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
            info = ydl.extract_info(url, download=True)
        return info or {}
