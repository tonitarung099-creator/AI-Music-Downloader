from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from yt_dlp import YoutubeDL


NOISE_TERMS = {
    "official", "video", "music", "audio", "lyrics", "lyric", "hd", "hq",
    "mv", "visualizer", "topic", "records", "recordings",
}

UNDESIRED_VARIANTS = {
    "live", "cover", "karaoke", "instrumental", "remix", "sped up", "sped-up",
    "slowed", "reverb", "nightcore", "8d", "bass boosted",
}


@dataclass(slots=True)
class Candidate:
    url: str
    title: str
    uploader: str = ""
    duration: float | None = None
    webpage_url: str = ""
    score: float = 0.0
    raw: dict[str, Any] | None = None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[\[\(].*?[\]\)]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [w for w in text.split() if w not in NOISE_TERMS]
    return " ".join(words)


def _tokens(text: str) -> set[str]:
    return set(normalize(text).split())


def _duration_score(expected: float | None, actual: float | None) -> float:
    if not expected or not actual:
        return 0.0
    delta = abs(expected - actual)
    if delta <= 2:
        return 0.18
    if delta <= 5:
        return 0.12
    if delta <= 12:
        return 0.05
    if delta >= 45:
        return -0.20
    return -0.05


def score_candidate(query: str, candidate: Candidate, expected_duration: float | None = None) -> float:
    nq = normalize(query)
    nt = normalize(candidate.title)
    nu = normalize(candidate.uploader)

    ratio = SequenceMatcher(None, nq, nt).ratio()
    query_tokens = _tokens(query)
    candidate_tokens = _tokens(candidate.title + " " + candidate.uploader)
    overlap = len(query_tokens & candidate_tokens) / max(1, len(query_tokens))

    score = (ratio * 0.52) + (overlap * 0.38)
    score += _duration_score(expected_duration, candidate.duration)

    query_lower = query.lower()
    full_lower = f"{candidate.title} {candidate.uploader}".lower()
    for term in UNDESIRED_VARIANTS:
        if term in full_lower and term not in query_lower:
            score -= 0.18

    if "official audio" in full_lower or candidate.uploader.lower().endswith(" - topic"):
        score += 0.08
    if "official" in full_lower and "audio" in full_lower:
        score += 0.05

    return max(-1.0, min(1.5, score))


def rank_candidates(query: str, entries: list[dict[str, Any]], expected_duration: float | None = None) -> list[Candidate]:
    ranked: list[Candidate] = []
    for entry in entries:
        if not entry:
            continue
        webpage_url = entry.get("webpage_url") or entry.get("url") or ""
        video_id = entry.get("id")
        if webpage_url and not webpage_url.startswith("http") and video_id:
            webpage_url = f"https://www.youtube.com/watch?v={video_id}"
        elif not webpage_url and video_id:
            webpage_url = f"https://www.youtube.com/watch?v={video_id}"

        candidate = Candidate(
            url=webpage_url,
            webpage_url=webpage_url,
            title=entry.get("title") or "",
            uploader=entry.get("uploader") or entry.get("channel") or "",
            duration=entry.get("duration"),
            raw=entry,
        )
        candidate.score = score_candidate(query, candidate, expected_duration)
        ranked.append(candidate)

    ranked.sort(key=lambda c: c.score, reverse=True)
    return ranked


def search_youtube(query: str, limit: int = 8, expected_duration: float | None = None) -> list[Candidate]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "noplaylist": True,
        "socket_timeout": 15,
        "retries": 2,
        "extractor_retries": 1,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    entries = list((info or {}).get("entries") or [])
    return rank_candidates(query, entries, expected_duration)


def is_ambiguous(ranked: list[Candidate]) -> bool:
    if not ranked:
        return False
    if len(ranked) == 1:
        return ranked[0].score < 0.58
    top, second = ranked[0], ranked[1]
    return top.score < 0.72 or math.isclose(top.score, second.score, abs_tol=0.07)
