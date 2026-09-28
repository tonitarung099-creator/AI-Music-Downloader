from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


def _new_id() -> str:
    return uuid4().hex


class TrackStatus(str, Enum):
    QUEUED = "Menunggu"
    SEARCHING = "Mencari"
    DOWNLOADING = "Mengunduh"
    PAUSED = "Dijeda"
    DONE = "Selesai"
    FAILED = "Gagal"
    CANCELLED = "Dibatalkan"


@dataclass(slots=True)
class TrackRequest:
    index: int
    query: str
    source: str = "manual"
    direct_url: str | None = None
    title: str | None = None
    artist: str | None = None
    duration: float | None = None
    status: TrackStatus = TrackStatus.QUEUED
    progress: float = 0.0
    error: str = ""
    resolved_url: str | None = None
    resolved_title: str | None = None
    job_id: str = field(default_factory=_new_id)
    batch_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.query
