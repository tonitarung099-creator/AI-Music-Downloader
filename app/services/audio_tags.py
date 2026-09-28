from __future__ import annotations

from pathlib import Path

from app.models import TrackRequest


def _fallback_title_artist(track: TrackRequest) -> tuple[str, str]:
    title = (track.title or "").strip()
    artist = (track.artist or "").strip()
    if title:
        return title, artist

    query = (track.query or "").strip()
    for separator in (" - ", " – ", " — "):
        if separator in query:
            left, right = query.split(separator, 1)
            if left.strip() and right.strip():
                return right.strip(), artist or left.strip()
    return query, artist


def apply_audio_tags(path: str, track: TrackRequest) -> str:
    """Write known metadata when the container is supported by Mutagen.

    Returns an empty string on success/no-op, or a human-readable warning. Tagging
    is deliberately non-fatal: a verified audio file remains valid even when its
    container cannot be tagged by Mutagen.
    """
    target = Path(path).expanduser()
    if not target.exists():
        return "file tidak ditemukan saat tagging"

    try:
        import mutagen
    except Exception as exc:
        return f"Mutagen tidak tersedia: {exc}"

    try:
        audio = mutagen.File(str(target), easy=True)
    except Exception as exc:
        return f"metadata tidak dapat dibuka: {exc}"
    if audio is None:
        return "container ini belum mendukung tagging metadata"

    title, artist = _fallback_title_artist(track)
    album = str(track.metadata.get("album") or "").strip()
    track_number = track.metadata.get("track_number")
    year = track.metadata.get("year")

    try:
        if title:
            audio["title"] = [title]
        if artist:
            audio["artist"] = [artist]
        if album:
            audio["album"] = [album]
        if track_number not in (None, ""):
            audio["tracknumber"] = [str(track_number)]
        if year not in (None, ""):
            audio["date"] = [str(year)]
        audio.save()
    except Exception as exc:
        return f"tag metadata gagal disimpan: {exc}"
    return ""
