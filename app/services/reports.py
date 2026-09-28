from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from app.services.diagnostics import redact_text, sanitize_mapping


REPORT_COLUMNS = (
    "job_id",
    "urutan",
    "permintaan",
    "judul",
    "artis",
    "sumber",
    "status",
    "progress",
    "hasil_judul",
    "hasil_url",
    "file",
    "container",
    "codec",
    "durasi",
    "ukuran_byte",
    "alasan_pemilihan",
    "error_code",
    "error",
)


def track_report_record(track: object) -> dict[str, object]:
    metadata = sanitize_mapping(getattr(track, "metadata", {}) or {})
    if not isinstance(metadata, dict):
        metadata = {}
    status = getattr(getattr(track, "status", None), "value", "")
    return {
        "job_id": str(getattr(track, "job_id", "")),
        "urutan": int(getattr(track, "index", 0) or 0),
        "permintaan": redact_text(getattr(track, "query", "")),
        "judul": redact_text(getattr(track, "title", "") or ""),
        "artis": redact_text(getattr(track, "artist", "") or ""),
        "sumber": str(getattr(track, "source", "")),
        "status": str(status),
        "progress": round(float(getattr(track, "progress", 0.0) or 0.0), 2),
        "hasil_judul": redact_text(getattr(track, "resolved_title", "") or ""),
        "hasil_url": redact_text(getattr(track, "resolved_url", "") or ""),
        "file": redact_text(getattr(track, "output_path", "") or ""),
        "container": str(metadata.get("verified_container") or ""),
        "codec": str(metadata.get("verified_audio_codec") or ""),
        "durasi": metadata.get("verified_duration"),
        "ukuran_byte": metadata.get("verified_size_bytes"),
        "alasan_pemilihan": redact_text(metadata.get("match_reason") or ""),
        "error_code": str(getattr(track, "error_code", "") or ""),
        "error": redact_text(getattr(track, "error", "") or ""),
    }


def batch_summary(tracks: Iterable[object]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    total = 0
    for track in tracks:
        total += 1
        status = str(getattr(getattr(track, "status", None), "value", "Tidak diketahui"))
        counter[status] += 1
    result = {"total": total}
    result.update(dict(counter))
    return result


def _atomic_target(path: str | Path) -> tuple[Path, Path]:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    return target, temp


def export_batch_csv(path: str | Path, tracks: Iterable[object]) -> Path:
    target, temp = _atomic_target(path)
    records = [track_report_record(track) for track in tracks]
    try:
        with temp.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        temp.replace(target)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def export_batch_json(path: str | Path, tracks: Iterable[object]) -> Path:
    target, temp = _atomic_target(path)
    items = list(tracks)
    payload = {
        "ringkasan": batch_summary(items),
        "item": [track_report_record(track) for track in items],
    }
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        temp.replace(target)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target
