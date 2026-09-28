from __future__ import annotations

import hashlib
import socket
from dataclasses import dataclass
from enum import Enum
from urllib.error import HTTPError, URLError


class ErrorKind(str, Enum):
    CANCELLED = "CANCELLED"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    VERIFICATION = "VERIFICATION"
    AUTH = "AUTH"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK = "NETWORK"
    SERVER = "SERVER"
    PERMANENT = "PERMANENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FailureInfo:
    kind: ErrorKind
    retryable: bool
    message: str


_PERMANENT_MARKERS = (
    "unsupported url",
    "invalid url",
    "url tidak valid",
    "video unavailable",
    "private video",
    "this video is private",
    "copyright",
    "not available in your country",
    "tidak menemukan kandidat youtube",
    "tidak ada kandidat youtube dengan bukti yang cukup cocok",
    "mode mp3 membutuhkan ffmpeg",
)
_VERIFICATION_MARKERS = (
    "ffprobe",
    "file final hasil download tidak ditemukan",
    "file hasil download kosong",
    "tidak memiliki stream audio",
    "durasi audio hasil download tidak valid",
    "downloader tidak mengembalikan identitas media yang valid",
)
_TRANSIENT_MARKERS = (
    "timed out",
    "timeout",
    "temporarily unavailable",
    "temporary failure",
    "connection reset",
    "connection aborted",
    "connection refused",
    "remote end closed connection",
    "network is unreachable",
    "name resolution",
    "dns",
    "http error 429",
    "too many requests",
    "http error 500",
    "http error 502",
    "http error 503",
    "http error 504",
)
_AUTH_MARKERS = (
    "http error 401",
    "http error 403",
    "unauthorized",
    "forbidden",
)


def classify_exception(exc: BaseException) -> FailureInfo:
    """Classify failures conservatively: only known transient failures auto-retry."""
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.casefold()

    if exc.__class__.__name__ == "DownloadCancelled":
        return FailureInfo(ErrorKind.CANCELLED, False, message)
    if exc.__class__.__name__ == "DownloadVerificationError" or any(
        marker in lowered for marker in _VERIFICATION_MARKERS
    ):
        return FailureInfo(ErrorKind.VERIFICATION, False, message)

    if isinstance(exc, HTTPError):
        if exc.code == 429:
            return FailureInfo(ErrorKind.RATE_LIMITED, True, message)
        if exc.code in {401, 403}:
            return FailureInfo(ErrorKind.AUTH, False, message)
        if 500 <= exc.code <= 599:
            return FailureInfo(ErrorKind.SERVER, True, message)
        if exc.code == 404:
            return FailureInfo(ErrorKind.NOT_FOUND, False, message)
        return FailureInfo(ErrorKind.PERMANENT, False, message)

    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionError, URLError)):
        return FailureInfo(ErrorKind.NETWORK, True, message)

    if any(marker in lowered for marker in _AUTH_MARKERS):
        return FailureInfo(ErrorKind.AUTH, False, message)
    if "429" in lowered or "too many requests" in lowered:
        return FailureInfo(ErrorKind.RATE_LIMITED, True, message)
    if any(marker in lowered for marker in _TRANSIENT_MARKERS):
        kind = ErrorKind.SERVER if "http error 5" in lowered else ErrorKind.NETWORK
        return FailureInfo(kind, True, message)
    if any(marker in lowered for marker in _PERMANENT_MARKERS):
        if "kandidat youtube" in lowered:
            return FailureInfo(ErrorKind.NOT_FOUND, False, message)
        kind = ErrorKind.INVALID_INPUT if "url" in lowered else ErrorKind.PERMANENT
        return FailureInfo(kind, False, message)

    return FailureInfo(ErrorKind.UNKNOWN, False, message)


def retry_delay_seconds(job_id: str, retry_index: int, *, base: float = 1.0, cap: float = 12.0) -> float:
    """Exponential backoff with deterministic jitter for stable tests and logs."""
    safe_index = max(0, int(retry_index))
    exponential = min(float(cap), float(base) * (2**safe_index))
    seed = hashlib.sha256(f"{job_id}:{safe_index}".encode("utf-8")).digest()
    fraction = int.from_bytes(seed[:2], "big") / 65535.0
    jitter = min(0.75, exponential * 0.20) * fraction
    return min(float(cap), exponential + jitter)
