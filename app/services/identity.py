from __future__ import annotations

import hashlib
import unicodedata
from urllib.parse import parse_qsl, parse_qs, urlencode, urlparse, urlunparse

from app.models import TrackRequest


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
SPOTIFY_HOSTS = {"open.spotify.com"}
TRACKING_QUERY_KEYS = {
    "feature",
    "si",
    "pp",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
}


def _normalized_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold().strip()
    return " ".join(text.split())


def query_fingerprint(query: str, *, artist: str | None = None, title: str | None = None) -> str:
    """Return a conservative fingerprint without erasing version words such as live/remix."""
    if artist and title:
        payload = f"{_normalized_text(artist)}\n{_normalized_text(title)}"
    else:
        payload = _normalized_text(query)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"query:{digest}"


def canonical_media_key(url: str) -> str | None:
    """Return a stable media/source identity for supported URLs.

    The key intentionally preserves media IDs instead of display ordering so queue
    reorder does not change identity. Unknown HTTP URLs are normalized
    conservatively and hashed.
    """
    text = (url or "").strip()
    if not text:
        return None
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None

    host = parsed.hostname.lower().rstrip(".")
    parts = [part for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query, keep_blank_values=False)

    if host in SPOTIFY_HOSTS and len(parts) >= 2:
        kind = parts[0].lower()
        source_id = parts[1].strip()
        if kind in {"track", "album", "playlist"} and source_id:
            return f"spotify:{kind}:{source_id}"

    if host in YOUTUBE_HOSTS:
        playlist_id = next((x.strip() for x in query.get("list", []) if str(x).strip()), "")
        video_id = ""
        if host == "youtu.be" and parts:
            video_id = parts[0].strip()
        elif parsed.path.rstrip("/").lower() == "/watch":
            video_id = next((x.strip() for x in query.get("v", []) if str(x).strip()), "")
        elif len(parts) >= 2 and parts[0].lower() in {"shorts", "embed"}:
            video_id = parts[1].strip()

        if video_id:
            return f"youtube:video:{video_id}"
        if playlist_id:
            return f"youtube:playlist:{playlist_id}"

    filtered_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered in TRACKING_QUERY_KEYS or lowered.startswith("utm_"):
            continue
        filtered_query.append((key, value))
    filtered_query.sort()

    try:
        port = parsed.port
    except ValueError:
        return None
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    netloc = host if not port or default_port else f"{host}:{port}"
    normalized = urlunparse(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path or "/",
            "",
            urlencode(filtered_query, doseq=True),
            "",
        )
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"url:{digest}"


def track_dedup_key(track: TrackRequest) -> str:
    if track.dedup_key:
        return track.dedup_key

    metadata_source = track.metadata.get("canonical_source_url") or track.metadata.get("spotify_url")
    for candidate in (metadata_source, track.direct_url):
        if candidate:
            key = canonical_media_key(str(candidate))
            if key:
                return key

    return query_fingerprint(track.query, artist=track.artist, title=track.title)
