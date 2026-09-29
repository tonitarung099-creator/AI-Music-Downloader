from __future__ import annotations

import json
import subprocess
import tempfile
from importlib import metadata, resources
from pathlib import Path
from typing import Any, Callable


class RuntimeSelfTestError(RuntimeError):
    """Raised when the portable runtime cannot prove a required capability."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


def portable_tool_paths(root: Path) -> dict[str, Path]:
    tools = Path(root) / "tools"
    return {
        "ffmpeg": tools / "ffmpeg.exe",
        "ffprobe": tools / "ffprobe.exe",
        "deno": tools / "deno.exe",
    }


def _run_checked(
    command: list[str],
    *,
    timeout: float,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            command,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeSelfTestError(
            f"Runtime timeout setelah {timeout:g} detik: {Path(command[0]).name}"
        ) from exc
    except OSError as exc:
        raise RuntimeSelfTestError(
            f"Runtime tidak dapat dijalankan: {Path(command[0]).name}: {exc}"
        ) from exc

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if len(details) > 500:
            details = details[:500] + "..."
        raise RuntimeSelfTestError(
            f"Runtime gagal ({result.returncode}): {Path(command[0]).name}: {details}"
        )
    return result


def _ensure_file(path: Path, label: str) -> None:
    try:
        valid = path.is_file() and path.stat().st_size > 0
    except OSError:
        valid = False
    if not valid:
        raise RuntimeSelfTestError(f"{label} tidak menghasilkan file valid: {path}")


def _verify_ejs_bundle() -> str:
    try:
        version = metadata.version("yt-dlp-ejs")
    except metadata.PackageNotFoundError as exc:
        raise RuntimeSelfTestError("Paket yt-dlp-ejs tidak ditemukan di runtime frozen.") from exc

    try:
        root = resources.files("yt_dlp_ejs")
        entries = list(root.iterdir())
    except Exception as exc:  # importlib.resources backend can vary when frozen
        raise RuntimeSelfTestError("Resource yt-dlp-ejs tidak dapat dibaca.") from exc

    if not entries:
        raise RuntimeSelfTestError("Resource yt-dlp-ejs kosong.")
    return version


def run_portable_runtime_self_test(
    root: Path,
    *,
    timeout: float = 15.0,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Exercise the exact bundled tools without relying on the system PATH.

    The test is intentionally local/offline: it checks executable versions,
    creates a tiny WAV fixture, converts it to M4A/AAC, and asks ffprobe to
    confirm that an audio stream exists.  This catches missing/broken ffmpeg,
    ffprobe, Deno, and EJS packaging before a portable ZIP is published.
    """

    root = Path(root).resolve()
    paths = portable_tool_paths(root)
    for label, path in paths.items():
        if not path.is_file():
            raise RuntimeSelfTestError(f"Tool wajib tidak ditemukan: {label}: {path}")

    ffmpeg_version = _run_checked(
        [str(paths["ffmpeg"]), "-version"], timeout=timeout, runner=runner
    )
    ffprobe_version = _run_checked(
        [str(paths["ffprobe"]), "-version"], timeout=timeout, runner=runner
    )
    deno_version = _run_checked(
        [str(paths["deno"]), "--version"], timeout=timeout, runner=runner
    )
    ejs_version = _verify_ejs_bundle()

    with tempfile.TemporaryDirectory(prefix="ai-music-downloader-self-test-") as temp_dir:
        temp = Path(temp_dir)
        wav_path = temp / "fixture.wav"
        m4a_path = temp / "fixture.m4a"

        _run_checked(
            [
                str(paths["ffmpeg"]),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:duration=0.25",
                "-c:a",
                "pcm_s16le",
                str(wav_path),
            ],
            timeout=timeout,
            runner=runner,
        )
        _ensure_file(wav_path, "FFmpeg fixture")

        _run_checked(
            [
                str(paths["ffmpeg"]),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(wav_path),
                "-vn",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                str(m4a_path),
            ],
            timeout=timeout,
            runner=runner,
        )
        _ensure_file(m4a_path, "FFmpeg conversion")

        probe = _run_checked(
            [
                str(paths["ffprobe"]),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type,codec_name",
                "-of",
                "json",
                str(m4a_path),
            ],
            timeout=timeout,
            runner=runner,
        )
        try:
            payload = json.loads(probe.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeSelfTestError("ffprobe mengembalikan JSON tidak valid.") from exc
        streams = payload.get("streams")
        if not isinstance(streams, list) or not any(
            isinstance(stream, dict) and stream.get("codec_type") == "audio"
            for stream in streams
        ):
            raise RuntimeSelfTestError("ffprobe tidak menemukan stream audio hasil konversi.")

    def first_line(value: str) -> str:
        return (value or "").splitlines()[0].strip() if value else ""

    return {
        "ffmpeg": first_line(ffmpeg_version.stdout or ffmpeg_version.stderr),
        "ffprobe": first_line(ffprobe_version.stdout or ffprobe_version.stderr),
        "deno": first_line(deno_version.stdout or deno_version.stderr),
        "yt_dlp_ejs": ejs_version,
        "audio_fixture": "ok",
        "root": str(root),
    }
