from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
from typing import Any

from yt_dlp import YoutubeDL


NOISE_TERMS = {
    "official", "video", "music", "audio", "lyrics", "lyric", "hd", "hq",
    "mv", "visualizer", "topic", "records", "recordings",
}

VERSION_PHRASES = {
    "live",
    "cover",
    "karaoke",
    "instrumental",
    "remix",
    "sped up",
    "sped-up",
    "slowed",
    "reverb",
    "nightcore",
    "8d",
    "bass boosted",
    "acoustic",
}

AUTO_MATCH_SCORE = 0.78
AUTO_MATCH_MARGIN = 0.10
MIN_REVIEW_SCORE = 0.48
GEMINI_HARD_FLOOR = 0.48


@dataclass(slots=True)
class Candidate:
    url: str
    title: str
    uploader: str = ""
    duration: float | None = None
    webpage_url: str = ""
    score: float = 0.0
    raw: dict[str, Any] | None = None


class MatchState(str, Enum):
    MATCHED = "MATCHED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NO_MATCH = "NO_MATCH"


@dataclass(slots=True)
class MatchDecision:
    state: MatchState
    candidate: Candidate | None
    candidates: list[Candidate]
    top_score: float = 0.0
    margin: float = 0.0
    reason: str = ""


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _plain_words(text: str) -> str:
    text = _strip_accents(text).casefold()
    chars: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        chars.append(ch if category[:1] in {"L", "N"} else " ")
    return " ".join("".join(chars).split())


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    haystack = normalized_text.split()
    needle = _plain_words(phrase).split()
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(haystack[pos : pos + width] == needle for pos in range(len(haystack) - width + 1))


def extract_versions(text: str) -> set[str]:
    normalized = _plain_words(text)
    found: set[str] = set()
    for phrase in VERSION_PHRASES:
        if _contains_phrase(normalized, phrase):
            found.add(_plain_words(phrase))
    return found


def _normalize_brackets(text: str) -> str:
    pattern = re.compile(r"([\(\[\{])([^\)\]\}]*)([\)\]\}])")

    def replace(match: re.Match[str]) -> str:
        inner = match.group(2)
        normalized = _plain_words(inner)
        tokens = set(normalized.split())
        if extract_versions(inner):
            return f" {inner} "
        if tokens and tokens.issubset(NOISE_TERMS):
            return " "
        return f" {inner} "

    return pattern.sub(replace, text or "")


def normalize(text: str) -> str:
    """Normalize labels while preserving Unicode letters and requested versions."""
    normalized = _plain_words(_normalize_brackets(text))
    words = [word for word in normalized.split() if word not in NOISE_TERMS]
    return " ".join(words)


def _tokens(text: str) -> set[str]:
    return set(normalize(text).split())


def _split_artist_title(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    parts = re.split(r"\s+[\-–—]\s+", raw, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return normalize(parts[0]), normalize(parts[1])
    return "", normalize(raw)


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


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
    query_artist, query_title = _split_artist_title(query)
    candidate_artist, candidate_title = _split_artist_title(candidate.title)

    full_ratio = _similarity(nq, nt)
    title_ratio = _similarity(query_title or nq, candidate_title or nt)
    query_tokens = _tokens(query)
    candidate_tokens = _tokens(candidate.title + " " + candidate.uploader)
    overlap = len(query_tokens & candidate_tokens) / max(1, len(query_tokens))

    artist_evidence = 0.0
    if query_artist:
        title_artist_score = _similarity(query_artist, candidate_artist)
        uploader_score = _similarity(query_artist, nu)
        uploader_overlap = len(set(query_artist.split()) & set(nu.split())) / max(1, len(query_artist.split()))
        artist_evidence = max(title_artist_score, uploader_score, uploader_overlap)

    score = (full_ratio * 0.28) + (title_ratio * 0.34) + (overlap * 0.20)
    if query_artist:
        score += artist_evidence * 0.18
    else:
        score += full_ratio * 0.08
    score += _duration_score(expected_duration, candidate.duration)

    requested_versions = extract_versions(query)
    candidate_versions = extract_versions(candidate.title)
    unexpected_versions = candidate_versions - requested_versions
    missing_versions = requested_versions - candidate_versions
    score -= min(0.44, 0.22 * len(unexpected_versions))
    score -= min(0.36, 0.18 * len(missing_versions))

    full_plain = _plain_words(f"{candidate.title} {candidate.uploader}")
    uploader_plain = _plain_words(candidate.uploader)
    if _contains_phrase(full_plain, "official audio") and (not query_artist or artist_evidence >= 0.45):
        score += 0.05
    if uploader_plain.endswith(" topic") and (not query_artist or artist_evidence >= 0.45):
        score += 0.06

    # Hard evidence guard: when an artist was explicitly supplied but is absent
    # from both title and uploader, a matching song title alone is not enough.
    if query_artist and artist_evidence < 0.18:
        score -= 0.20

    return max(-1.0, min(1.5, score))


def rank_candidates(query: str, entries: list[dict[str, Any]], expected_duration: float | None = None) -> list[Candidate]:
    ranked: list[Candidate] = []
    for entry in entries:
        if not entry:
            continue
        webpage_url = entry.get("webpage_url") or entry.get("url") or ""
        video_id = entry.get("id")
        if webpage_url and not str(webpage_url).startswith("http") and video_id:
            webpage_url = f"https://www.youtube.com/watch?v={video_id}"
        elif not webpage_url and video_id:
            webpage_url = f"https://www.youtube.com/watch?v={video_id}"

        candidate = Candidate(
            url=str(webpage_url),
            webpage_url=str(webpage_url),
            title=str(entry.get("title") or ""),
            uploader=str(entry.get("uploader") or entry.get("channel") or ""),
            duration=entry.get("duration"),
            raw=entry,
        )
        candidate.score = score_candidate(query, candidate, expected_duration)
        ranked.append(candidate)

    ranked.sort(key=lambda candidate: candidate.score, reverse=True)
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


def decide_match(ranked: list[Candidate]) -> MatchDecision:
    if not ranked:
        return MatchDecision(MatchState.NO_MATCH, None, [], reason="Tidak ada kandidat.")

    top = ranked[0]
    second_score = ranked[1].score if len(ranked) > 1 else -1.0
    margin = top.score - second_score if len(ranked) > 1 else math.inf

    if top.score < MIN_REVIEW_SCORE:
        return MatchDecision(
            MatchState.NO_MATCH,
            None,
            ranked[:6],
            top_score=top.score,
            margin=margin,
            reason=f"Bukti kandidat terlalu lemah ({top.score:.2f}).",
        )

    if top.score >= AUTO_MATCH_SCORE and (len(ranked) == 1 or margin >= AUTO_MATCH_MARGIN):
        return MatchDecision(
            MatchState.MATCHED,
            top,
            ranked[:6],
            top_score=top.score,
            margin=margin,
            reason="Kandidat teratas memiliki bukti dan margin yang cukup.",
        )

    return MatchDecision(
        MatchState.NEEDS_REVIEW,
        top,
        ranked[:6],
        top_score=top.score,
        margin=margin,
        reason="Kandidat cukup masuk akal tetapi belum aman untuk dipilih otomatis.",
    )


def is_ambiguous(ranked: list[Candidate]) -> bool:
    """Backward-compatible helper: anything not safely auto-matched is ambiguous."""
    return decide_match(ranked).state != MatchState.MATCHED


def candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "url": candidate.url,
        "title": candidate.title,
        "uploader": candidate.uploader,
        "duration": candidate.duration,
        "score": round(float(candidate.score), 6),
        "versions": sorted(extract_versions(candidate.title)),
    }
