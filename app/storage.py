from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.config import app_root
from app.models import TrackRequest, TrackStatus
from app.services.identity import track_dedup_key


SCHEMA_VERSION = 1
ACTIVE_RUNTIME_STATUSES = {
    TrackStatus.SEARCHING.name,
    TrackStatus.DOWNLOADING.name,
    TrackStatus.PAUSED.name,
    TrackStatus.RETRY_WAIT.name,
}


class QueueStorageError(RuntimeError):
    pass


@dataclass(slots=True)
class DuplicateTrack:
    dedup_key: str
    existing_job_id: str
    status: str
    display_name: str
    output_path: str | None = None


@dataclass(slots=True)
class AddTracksResult:
    added: list[TrackRequest]
    duplicates: list[DuplicateTrack]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _metadata_json(value: dict) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return "{}"


def _load_metadata(value: str | None) -> dict:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _status_from_db(value: str) -> TrackStatus:
    try:
        return TrackStatus[value]
    except (KeyError, TypeError):
        return TrackStatus.QUEUED


class QueueRepository:
    """SQLite-backed source of truth for queue, history, and completed manifest."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else app_root() / "data" / "queue.sqlite3"
        self.path = self.path.expanduser().resolve()
        self._lock = threading.RLock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()
        except (OSError, sqlite3.Error) as exc:
            raise QueueStorageError(f"Gagal membuka database antrean: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise QueueStorageError(
                    f"Schema database versi {current} lebih baru daripada aplikasi ({SCHEMA_VERSION})."
                )

            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")

            if current < 1:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_id TEXT PRIMARY KEY,
                        position INTEGER NOT NULL,
                        batch_id TEXT NOT NULL DEFAULT '',
                        query TEXT NOT NULL,
                        source TEXT NOT NULL,
                        direct_url TEXT,
                        title TEXT,
                        artist TEXT,
                        duration REAL,
                        status TEXT NOT NULL,
                        progress REAL NOT NULL DEFAULT 0,
                        error TEXT NOT NULL DEFAULT '',
                        error_code TEXT NOT NULL DEFAULT '',
                        error_retryable INTEGER NOT NULL DEFAULT 0,
                        resolved_url TEXT,
                        resolved_title TEXT,
                        output_path TEXT,
                        dedup_key TEXT NOT NULL,
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        is_removed INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        completed_at TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_jobs_active_position
                        ON jobs(is_removed, position);
                    CREATE INDEX IF NOT EXISTS idx_jobs_dedup_active
                        ON jobs(dedup_key, is_removed);
                    CREATE INDEX IF NOT EXISTS idx_jobs_status
                        ON jobs(status, is_removed);

                    CREATE TABLE IF NOT EXISTS job_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT NOT NULL,
                        event TEXT NOT NULL,
                        status TEXT,
                        detail TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_history_job
                        ON job_history(job_id, id DESC);

                    CREATE TABLE IF NOT EXISTS manifest (
                        dedup_key TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        output_path TEXT,
                        resolved_url TEXT,
                        resolved_title TEXT,
                        display_name TEXT NOT NULL,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        completed_at TEXT NOT NULL
                    );

                    PRAGMA user_version = 1;
                    """
                )

    def _job_params(self, track: TrackRequest, *, position: int | None = None) -> dict:
        now = _utc_now()
        dedup_key = track.dedup_key or track_dedup_key(track)
        track.dedup_key = dedup_key
        return {
            "job_id": track.job_id,
            "position": int(position if position is not None else track.index),
            "batch_id": track.batch_id or "",
            "query": track.query,
            "source": track.source,
            "direct_url": track.direct_url,
            "title": track.title,
            "artist": track.artist,
            "duration": track.duration,
            "status": track.status.name,
            "progress": float(track.progress),
            "error": track.error or "",
            "error_code": track.error_code or "",
            "error_retryable": 1 if track.error_retryable else 0,
            "resolved_url": track.resolved_url,
            "resolved_title": track.resolved_title,
            "output_path": track.output_path,
            "dedup_key": dedup_key,
            "attempt_count": int(track.attempt_count),
            "metadata_json": _metadata_json(track.metadata),
            "created_at": now,
            "updated_at": now,
            "completed_at": now if track.status == TrackStatus.DONE else None,
        }

    @staticmethod
    def _upsert_job(conn: sqlite3.Connection, params: dict) -> None:
        conn.execute(
            """
            INSERT INTO jobs (
                job_id, position, batch_id, query, source, direct_url, title, artist,
                duration, status, progress, error, error_code, error_retryable,
                resolved_url, resolved_title, output_path, dedup_key, attempt_count,
                metadata_json, is_removed, created_at, updated_at, completed_at
            ) VALUES (
                :job_id, :position, :batch_id, :query, :source, :direct_url, :title, :artist,
                :duration, :status, :progress, :error, :error_code, :error_retryable,
                :resolved_url, :resolved_title, :output_path, :dedup_key, :attempt_count,
                :metadata_json, 0, :created_at, :updated_at, :completed_at
            )
            ON CONFLICT(job_id) DO UPDATE SET
                position = excluded.position,
                batch_id = excluded.batch_id,
                query = excluded.query,
                source = excluded.source,
                direct_url = excluded.direct_url,
                title = excluded.title,
                artist = excluded.artist,
                duration = excluded.duration,
                status = excluded.status,
                progress = excluded.progress,
                error = excluded.error,
                error_code = excluded.error_code,
                error_retryable = excluded.error_retryable,
                resolved_url = excluded.resolved_url,
                resolved_title = excluded.resolved_title,
                output_path = excluded.output_path,
                dedup_key = excluded.dedup_key,
                attempt_count = excluded.attempt_count,
                metadata_json = excluded.metadata_json,
                is_removed = 0,
                updated_at = excluded.updated_at,
                completed_at = excluded.completed_at
            """,
            params,
        )

    @staticmethod
    def _record_event(
        conn: sqlite3.Connection,
        job_id: str,
        event: str,
        status: str | None,
        detail: str = "",
    ) -> None:
        conn.execute(
            "INSERT INTO job_history(job_id, event, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, event, status, detail or "", _utc_now()),
        )

    @staticmethod
    def _upsert_manifest(conn: sqlite3.Connection, track: TrackRequest) -> None:
        if track.status != TrackStatus.DONE:
            return
        dedup_key = track.dedup_key or track_dedup_key(track)
        conn.execute(
            """
            INSERT INTO manifest(
                dedup_key, job_id, output_path, resolved_url, resolved_title,
                display_name, metadata_json, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedup_key) DO UPDATE SET
                job_id = excluded.job_id,
                output_path = excluded.output_path,
                resolved_url = excluded.resolved_url,
                resolved_title = excluded.resolved_title,
                display_name = excluded.display_name,
                metadata_json = excluded.metadata_json,
                completed_at = excluded.completed_at
            """,
            (
                dedup_key,
                track.job_id,
                track.output_path,
                track.resolved_url,
                track.resolved_title,
                track.display_name,
                _metadata_json(track.metadata),
                _utc_now(),
            ),
        )

    def add_tracks(self, tracks: Iterable[TrackRequest]) -> AddTracksResult:
        added: list[TrackRequest] = []
        duplicates: list[DuplicateTrack] = []
        items = list(tracks)
        if not items:
            return AddTracksResult(added, duplicates)

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), 0) AS max_position FROM jobs WHERE is_removed = 0"
            ).fetchone()
            next_position = int(row["max_position"] or 0) + 1

            for track in items:
                key = track.dedup_key or track_dedup_key(track)
                track.dedup_key = key

                existing = conn.execute(
                    """
                    SELECT job_id, status, output_path, title, artist, query
                    FROM jobs
                    WHERE dedup_key = ? AND is_removed = 0
                    ORDER BY position ASC
                    LIMIT 1
                    """,
                    (key,),
                ).fetchone()
                if existing is not None:
                    display = (
                        f"{existing['artist']} - {existing['title']}"
                        if existing["artist"] and existing["title"]
                        else existing["title"] or existing["query"]
                    )
                    duplicates.append(
                        DuplicateTrack(
                            dedup_key=key,
                            existing_job_id=str(existing["job_id"]),
                            status=_status_from_db(str(existing["status"])).value,
                            display_name=str(display),
                            output_path=existing["output_path"],
                        )
                    )
                    continue

                manifest = conn.execute(
                    "SELECT job_id, output_path, display_name FROM manifest WHERE dedup_key = ? LIMIT 1",
                    (key,),
                ).fetchone()
                if manifest is not None:
                    duplicates.append(
                        DuplicateTrack(
                            dedup_key=key,
                            existing_job_id=str(manifest["job_id"]),
                            status=TrackStatus.DONE.value,
                            display_name=str(manifest["display_name"]),
                            output_path=manifest["output_path"],
                        )
                    )
                    continue

                track.index = next_position
                params = self._job_params(track, position=next_position)
                self._upsert_job(conn, params)
                self._record_event(conn, track.job_id, "added", track.status.name, track.display_name)
                added.append(track)
                next_position += 1

        return AddTracksResult(added, duplicates)

    def checkpoint(self, track: TrackRequest, *, event: str | None = None, detail: str = "") -> None:
        try:
            with self._lock, self._connect() as conn:
                self._upsert_job(conn, self._job_params(track))
                if event:
                    self._record_event(conn, track.job_id, event, track.status.name, detail)
                self._upsert_manifest(conn, track)
        except sqlite3.Error as exc:
            raise QueueStorageError(f"Gagal menyimpan checkpoint antrean: {exc}") from exc

    def checkpoint_many(self, tracks: Iterable[TrackRequest], *, event: str | None = None) -> None:
        items = list(tracks)
        if not items:
            return
        try:
            with self._lock, self._connect() as conn:
                for track in items:
                    self._upsert_job(conn, self._job_params(track))
                    if event:
                        self._record_event(conn, track.job_id, event, track.status.name, "")
                    self._upsert_manifest(conn, track)
        except sqlite3.Error as exc:
            raise QueueStorageError(f"Gagal menyimpan antrean: {exc}") from exc

    def restore_queue(self) -> list[TrackRequest]:
        """Restore active queue and convert stale runtime states to INTERRUPTED."""
        try:
            with self._lock, self._connect() as conn:
                active_rows = conn.execute(
                    """
                    SELECT job_id, status
                    FROM jobs
                    WHERE is_removed = 0 AND status IN (?, ?, ?, ?)
                    """,
                    tuple(ACTIVE_RUNTIME_STATUSES),
                ).fetchall()
                for row in active_rows:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET status = ?, error = ?, error_code = ?, error_retryable = 1, updated_at = ?
                        WHERE job_id = ?
                        """,
                        (
                            TrackStatus.INTERRUPTED.name,
                            "Proses sebelumnya terputus sebelum selesai.",
                            "INTERRUPTED",
                            _utc_now(),
                            row["job_id"],
                        ),
                    )
                    self._record_event(
                        conn,
                        str(row["job_id"]),
                        "restored_interrupted",
                        TrackStatus.INTERRUPTED.name,
                        f"Status lama: {row['status']}",
                    )

                rows = conn.execute(
                    "SELECT * FROM jobs WHERE is_removed = 0 ORDER BY position ASC, created_at ASC"
                ).fetchall()
        except sqlite3.Error as exc:
            raise QueueStorageError(f"Gagal memulihkan antrean: {exc}") from exc

        tracks: list[TrackRequest] = []
        for row in rows:
            status = _status_from_db(str(row["status"]))
            track = TrackRequest(
                index=int(row["position"]),
                query=str(row["query"]),
                source=str(row["source"]),
                direct_url=row["direct_url"],
                title=row["title"],
                artist=row["artist"],
                duration=row["duration"],
                status=status,
                progress=float(row["progress"] or 0.0),
                error=str(row["error"] or ""),
                resolved_url=row["resolved_url"],
                resolved_title=row["resolved_title"],
                job_id=str(row["job_id"]),
                batch_id=str(row["batch_id"] or ""),
                dedup_key=str(row["dedup_key"] or ""),
                output_path=row["output_path"],
                attempt_count=int(row["attempt_count"] or 0),
                error_code=str(row["error_code"] or ""),
                error_retryable=bool(row["error_retryable"]),
                metadata=_load_metadata(row["metadata_json"]),
            )
            tracks.append(track)
        return tracks

    def remove_jobs(self, job_ids: Iterable[str], *, detail: str = "Dihapus dari antrean") -> int:
        ids = [str(job_id) for job_id in job_ids if str(job_id)]
        if not ids:
            return 0
        removed = 0
        try:
            with self._lock, self._connect() as conn:
                for job_id in ids:
                    row = conn.execute(
                        "SELECT status FROM jobs WHERE job_id = ? AND is_removed = 0",
                        (job_id,),
                    ).fetchone()
                    if row is None:
                        continue
                    conn.execute(
                        "UPDATE jobs SET is_removed = 1, updated_at = ? WHERE job_id = ?",
                        (_utc_now(), job_id),
                    )
                    self._record_event(conn, job_id, "removed", str(row["status"]), detail)
                    removed += 1
        except sqlite3.Error as exc:
            raise QueueStorageError(f"Gagal menghapus item antrean: {exc}") from exc
        return removed

    def reorder(self, ordered_job_ids: Iterable[str]) -> None:
        ids = [str(job_id) for job_id in ordered_job_ids if str(job_id)]
        try:
            with self._lock, self._connect() as conn:
                for position, job_id in enumerate(ids, start=1):
                    conn.execute(
                        "UPDATE jobs SET position = ?, updated_at = ? WHERE job_id = ? AND is_removed = 0",
                        (position, _utc_now(), job_id),
                    )
                    self._record_event(conn, job_id, "reordered", None, f"Posisi {position}")
        except sqlite3.Error as exc:
            raise QueueStorageError(f"Gagal menyimpan urutan antrean: {exc}") from exc

    def record_retry_requested(self, job_ids: Iterable[str]) -> None:
        ids = [str(job_id) for job_id in job_ids if str(job_id)]
        if not ids:
            return
        try:
            with self._lock, self._connect() as conn:
                for job_id in ids:
                    row = conn.execute(
                        "SELECT status FROM jobs WHERE job_id = ? AND is_removed = 0",
                        (job_id,),
                    ).fetchone()
                    if row is not None:
                        self._record_event(conn, job_id, "retry_requested", str(row["status"]), "")
        except sqlite3.Error as exc:
            raise QueueStorageError(f"Gagal mencatat retry: {exc}") from exc

    def history(self, *, limit: int = 200) -> list[dict]:
        safe_limit = max(1, min(5000, int(limit)))
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, job_id, event, status, detail, created_at FROM job_history ORDER BY id DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise QueueStorageError(f"Gagal membaca riwayat antrean: {exc}") from exc
        return [dict(row) for row in rows]

    def manifest_entry(self, dedup_key: str) -> dict | None:
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM manifest WHERE dedup_key = ? LIMIT 1",
                    (dedup_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise QueueStorageError(f"Gagal membaca manifest: {exc}") from exc
        return dict(row) if row is not None else None

    def active_job_ids(self) -> list[str]:
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    "SELECT job_id FROM jobs WHERE is_removed = 0 ORDER BY position ASC"
                ).fetchall()
        except sqlite3.Error as exc:
            raise QueueStorageError(f"Gagal membaca antrean aktif: {exc}") from exc
        return [str(row["job_id"]) for row in rows]
