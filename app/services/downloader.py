from __future__ import annotations

import json
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from yt_dlp import YoutubeDL

from app.config import app_root
from app.models import TrackRequest, TrackStatus
from app.services.gemini_agent import GeminiAgent
from app.services.matcher import (
    Candidate,
    MatchState,
    candidate_to_dict,
    decide_match,
    search_youtube,
)


ProgressCallback = Callable[[float, str], None]


class DownloadCancelled(RuntimeError):
    pass


class CandidateReviewRequired(RuntimeError):
    def __init__(self, message: str, candidates: list[Candidate]) -> None:
        super().__init__(message)
        self.candidates = list(candidates[:6])


class DownloadVerificationError(RuntimeError):
    pass


@dataclass(slots=True)
class DownloadResult:
    final_path: str
    source_id: str
    source_url: str
    title: str
    container: str
    audio_codec: str
    duration: float | None
    size_bytes: int
    verified: bool
    metadata_warning: str = ""


@dataclass(slots=True)
class AudioProbe:
    container: str
    audio_codec: str
    duration: float | None
    size_bytes: int


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

    @staticmethod
    def ffprobe_path() -> str | None:
        portable = app_root() / "tools" / "ffprobe.exe"
        if portable.exists():
            return str(portable)
        return shutil.which("ffprobe")

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

        decision = decide_match(ranked)
        track.metadata["match_state"] = decision.state.value
        track.metadata["match_top_score"] = round(decision.top_score, 6)
        track.metadata["match_margin"] = None if decision.margin == float("inf") else round(decision.margin, 6)
        track.metadata["match_reason"] = decision.reason

        if decision.state == MatchState.NO_MATCH:
            raise RuntimeError(
                "Tidak ada kandidat YouTube dengan bukti yang cukup cocok. "
                f"{decision.reason}"
            )

        if decision.state == MatchState.MATCHED and decision.candidate is not None:
            return decision.candidate

        if self.gemini and self.gemini.available:
            idx = self.gemini.choose_candidate(track.query, ranked, cancel_event=stop_event)
            if stop_event and stop_event.is_set():
                raise DownloadCancelled("Dibatalkan pengguna.")
            if idx is not None:
                chosen = ranked[idx]
                track.metadata["match_state"] = "MATCHED_GEMINI"
                track.metadata["match_reason"] = "Ambiguitas lokal dipilih Gemini di atas batas confidence dan evidence."
                return chosen

        raise CandidateReviewRequired(
            "Kandidat lagu masih ambigu dan perlu dipilih pengguna.",
            decision.candidates,
        )

    @staticmethod
    def _best_effort_output_path(
        info: dict,
        ydl: YoutubeDL,
        audio_mode: str,
        destination: Path,
    ) -> str | None:
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

        source_id = str(info.get("id") or "").strip()
        if source_id:
            try:
                expanded.extend(destination.glob(f"*[{source_id}].*"))
            except OSError:
                pass

        seen: set[str] = set()
        for candidate in expanded:
            try:
                resolved = candidate.expanduser().resolve()
            except OSError:
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            if resolved.suffix.lower() in {".part", ".ytdl", ".temp", ".tmp"}:
                continue
            try:
                if resolved.exists() and resolved.is_file() and resolved.stat().st_size > 0:
                    return str(resolved)
            except OSError:
                continue
        return None

    def _probe_audio(self, path: str) -> AudioProbe:
        target = Path(path).expanduser().resolve()
        try:
            size = target.stat().st_size
        except OSError as exc:
            raise DownloadVerificationError(f"File hasil download tidak dapat dibaca: {exc}") from exc
        if size <= 0:
            raise DownloadVerificationError("File hasil download kosong.")

        ffprobe = self.ffprobe_path()
        if not ffprobe:
            raise DownloadVerificationError(
                "FFprobe tidak tersedia untuk memverifikasi hasil audio. "
                "Gunakan paket portable lengkap dengan folder tools."
            )

        command = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration:stream=codec_type,codec_name",
            "-of",
            "json",
            str(target),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DownloadVerificationError(f"FFprobe gagal dijalankan: {exc}") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise DownloadVerificationError(
                "File hasil download gagal diverifikasi oleh FFprobe"
                + (f": {detail[-240:]}" if detail else ".")
            )

        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise DownloadVerificationError("Output FFprobe tidak valid.") from exc

        streams = payload.get("streams") or []
        audio_streams = [
            stream for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ]
        if not audio_streams:
            raise DownloadVerificationError("File hasil download tidak memiliki stream audio.")

        fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
        duration_raw = fmt.get("duration")
        try:
            duration = float(duration_raw) if duration_raw not in (None, "") else None
        except (TypeError, ValueError):
            duration = None
        if duration is not None and duration <= 0:
            raise DownloadVerificationError("Durasi audio hasil download tidak valid.")

        container = str(fmt.get("format_name") or target.suffix.lstrip(".") or "unknown")
        codec = str(audio_streams[0].get("codec_name") or "unknown")
        return AudioProbe(container=container, audio_codec=codec, duration=duration, size_bytes=size)

    def download(
        self,
        track: TrackRequest,
        output_dir: str,
        audio_mode: str,
        progress_cb: ProgressCallback | None = None,
        pause_event: threading.Event | None = None,
        stop_event: threading.Event | None = None,
    ) -> DownloadResult:
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
            track.metadata.pop("review_candidates", None)
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
                track.status = TrackStatus.POSTPROCESSING
                progress_cb(99.0, "Download selesai, memproses audio...")

        def postprocessor_hook(data: dict) -> None:
            if stop_event and stop_event.is_set():
                raise DownloadCancelled("Dibatalkan pengguna.")
            track.status = TrackStatus.POSTPROCESSING
            if progress_cb:
                status = str(data.get("status") or "").lower()
                if status == "started":
                    progress_cb(99.0, "Memproses format audio...")
                elif status == "finished":
                    progress_cb(99.0, "Pemrosesan audio selesai...")

        opts: dict = {
            # Original means audio-only source with no extra lossy transcode.
            "format": "bestaudio",
            "outtmpl": str(destination / "%(title).160B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "windowsfilenames": True,
            "overwrites": False,
            "continuedl": True,
            "retries": 0,
            "fragment_retries": 0,
            "extractor_retries": 1,
            "socket_timeout": 15,
            "progress_hooks": [hook],
            "postprocessor_hooks": [postprocessor_hook],
        }

        ffmpeg = self.ffmpeg_location()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg

        if audio_mode == "m4a":
            # Preference only. If M4A does not exist, keep the best original
            # audio stream instead of silently transcoding it to M4A.
            opts["format"] = "bestaudio[ext=m4a]/bestaudio"
        elif audio_mode == "mp3":
            if not ffmpeg:
                raise RuntimeError("Mode MP3 membutuhkan FFmpeg. Letakkan FFmpeg di tools/ atau PATH.")
            opts["format"] = "bestaudio"
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
            final_path = self._best_effort_output_path(info, ydl, audio_mode, destination)

        if stop_event and stop_event.is_set():
            raise DownloadCancelled("Dibatalkan pengguna.")
        if not info or not info.get("id"):
            raise DownloadVerificationError("Downloader tidak mengembalikan identitas media yang valid.")
        if not final_path:
            raise DownloadVerificationError("File final hasil download tidak ditemukan.")

        track.status = TrackStatus.VERIFYING
        if progress_cb:
            progress_cb(99.0, "Memverifikasi stream audio dengan FFprobe...")
        probe = self._probe_audio(final_path)

        track.output_path = final_path
        track.metadata["source_media_id"] = str(info.get("id") or "")
        if info.get("extractor_key"):
            track.metadata["source_extractor"] = str(info["extractor_key"])
        track.metadata["verified_container"] = probe.container
        track.metadata["verified_audio_codec"] = probe.audio_codec
        track.metadata["verified_duration"] = probe.duration
        track.metadata["verified_size_bytes"] = probe.size_bytes

        if progress_cb:
            progress_cb(100.0, "Audio terverifikasi.")

        return DownloadResult(
            final_path=final_path,
            source_id=str(info.get("id") or ""),
            source_url=str(info.get("webpage_url") or url),
            title=str(info.get("title") or track.resolved_title or track.display_name),
            container=probe.container,
            audio_codec=probe.audio_codec,
            duration=probe.duration,
            size_bytes=probe.size_bytes,
            verified=True,
        )


def serialize_review_candidates(candidates: list[Candidate]) -> list[dict]:
    return [candidate_to_dict(candidate) for candidate in candidates[:6]]
