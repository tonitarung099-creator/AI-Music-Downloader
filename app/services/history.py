from __future__ import annotations

import sqlite3
from pathlib import Path


class HistoryReadError(RuntimeError):
    pass


def read_job_history(
    database_path: str | Path,
    *,
    job_id: str | None = None,
    limit: int = 300,
) -> list[dict[str, object]]:
    path = Path(database_path).expanduser().resolve()
    bounded_limit = max(1, min(2000, int(limit)))
    try:
        conn = sqlite3.connect(path, timeout=3.0)
        conn.row_factory = sqlite3.Row
        try:
            if job_id:
                rows = conn.execute(
                    """
                    SELECT id, job_id, event, status, detail, created_at
                    FROM job_history
                    WHERE job_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (str(job_id), bounded_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, job_id, event, status, detail, created_at
                    FROM job_history
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (bounded_limit,),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise HistoryReadError(f"Riwayat tidak dapat dibaca: {exc}") from exc
