from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

import app.services.downloader as downloader_module
from app.config import AppConfig
from app.models import TrackRequest, TrackStatus
from app.services.audio_tags import apply_audio_tags
from app.services.downloader import (
    AudioProbe,
    CandidateReviewRequired,
    DownloadEngine,
    DownloadResult,
    DownloadVerificationError,
)
from app.services.gemini_agent import GeminiAgent
from app.services.matcher import Candidate, MatchState, decide_match, normalize, rank_candidates, score_candidate
from app.storage import QueueRepository
from app.workers import QueueWorker


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stage3_match_cases.json"


def _valid_result(path: Path, source_id: str = "fixture") -> DownloadResult:
    path.write_bytes(b"fixture-audio")
    return DownloadResult(
        final_path=str(path),
        source_id=source_id,
        source_url=f"https://www.youtube.com/watch?v={source_id}",
        title="Fixture",
        container="webm",
        audio_codec="opus",
        duration=200.0,
        size_bytes=path.stat().st_size,
        verified=True,
    )


def test_stage3_annotated_matching_dataset_has_zero_false_positive_auto_matches():
    cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(cases) >= 30

    false_positives = []
    for case in cases:
        ranked = rank_candidates(case["query"], case["entries"], case.get("duration"))
        decision = decide_match(ranked)
        expected = MatchState(case["expected"])
        assert decision.state == expected, case["name"]

        correct = case.get("correct")
        if expected == MatchState.MATCHED:
            assert decision.candidate is not None, case["name"]
            expected_id = case["entries"][correct]["id"]
            actual_id = (decision.candidate.raw or {}).get("id")
            if actual_id != expected_id:
                false_positives.append(case["name"])

    assert false_positives == []


def test_stage3_unicode_normalization_keeps_non_latin_text():
    assert normalize("東京 夜空") == "東京 夜空"
    assert normalize("아이유 - 밤편지")
    assert normalize("فيروز - نسم علينا الهوى")


def test_stage3_discover_channel_is_not_misread_as_cover():
    query = "M83 - Midnight City"
    normal = Candidate(url="a", title="M83 - Midnight City", uploader="Discover Records", duration=244)
    cover = Candidate(url="b", title="M83 - Midnight City Cover", uploader="Fan Cover", duration=244)
    assert score_candidate(query, normal, 244) > score_candidate(query, cover, 244)


def test_stage3_ambiguous_candidate_requires_review_without_gemini(monkeypatch):
    candidates = [
        Candidate(url="a", title="Artist - Song", uploader="Artist", duration=200, score=0.90),
        Candidate(url="b", title="Artist - Song", uploader="Artist", duration=200, score=0.89),
    ]
    monkeypatch.setattr(downloader_module, "search_youtube", lambda *args, **kwargs: candidates)
    engine = DownloadEngine()

    with pytest.raises(CandidateReviewRequired):
        engine.resolve_candidate(TrackRequest(index=1, query="Artist - Song", duration=200))


def test_stage3_review_item_does_not_block_later_job(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    first = TrackRequest(index=1, query="Ambiguous")
    second = TrackRequest(index=2, query="Clear")
    repo = QueueRepository(tmp_path / "queue.sqlite3")
    repo.add_tracks([first, second])

    result_path = tmp_path / "clear.webm"

    class FixtureEngine:
        def download(self, track, **kwargs):
            if track.job_id == first.job_id:
                raise CandidateReviewRequired(
                    "fixture review",
                    [Candidate(url="https://youtu.be/a", title="Candidate A", uploader="Channel", score=0.6)],
                )
            return _valid_result(result_path, "clear")

    worker = QueueWorker(
        [first, second],
        AppConfig(output_dir=str(tmp_path), max_retries=0),
        GeminiAgent([]),
        repository=repo,
    )
    worker.engine = FixtureEngine()
    worker.run()

    assert first.status == TrackStatus.NEEDS_REVIEW
    assert first.metadata["review_candidates"][0]["url"] == "https://youtu.be/a"
    assert second.status == TrackStatus.DONE


def test_stage3_done_requires_verified_download_result_and_real_file(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    track = TrackRequest(index=1, query="Fixture")
    worker = QueueWorker(
        [track],
        AppConfig(output_dir=str(tmp_path), max_retries=0),
        GeminiAgent([]),
    )

    class InvalidTypedEngine:
        def download(self, *args, **kwargs):
            return DownloadResult(
                final_path=str(tmp_path / "missing.webm"),
                source_id="fixture",
                source_url="https://example.test",
                title="Fixture",
                container="webm",
                audio_codec="opus",
                duration=1.0,
                size_bytes=10,
                verified=True,
            )

    worker.engine = InvalidTypedEngine()
    worker.run()
    assert track.status == TrackStatus.FAILED
    assert track.error_code == "VERIFICATION"


def test_stage3_ffprobe_requires_audio_stream(tmp_path, monkeypatch):
    target = tmp_path / "video-only.webm"
    target.write_bytes(b"not-empty")
    engine = DownloadEngine()
    monkeypatch.setattr(engine, "ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(
        downloader_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"streams": [{"codec_type": "video", "codec_name": "vp9"}], "format": {"duration": "10"}}),
            stderr="",
        ),
    )

    with pytest.raises(DownloadVerificationError):
        engine._probe_audio(str(target))


def test_stage3_ffprobe_returns_codec_container_duration_and_size(tmp_path, monkeypatch):
    target = tmp_path / "audio.webm"
    target.write_bytes(b"valid-audio-bytes")
    engine = DownloadEngine()
    monkeypatch.setattr(engine, "ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(
        downloader_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "streams": [{"codec_type": "audio", "codec_name": "opus"}],
                "format": {"duration": "123.5", "format_name": "matroska,webm"},
            }),
            stderr="",
        ),
    )

    probe = engine._probe_audio(str(target))
    assert probe.audio_codec == "opus"
    assert probe.container == "matroska,webm"
    assert probe.duration == pytest.approx(123.5)
    assert probe.size_bytes == target.stat().st_size


@pytest.mark.parametrize(
    ("audio_mode", "expected_format", "expect_postprocessor"),
    [
        ("original", "bestaudio", False),
        ("m4a", "bestaudio[ext=m4a]/bestaudio", False),
        ("mp3", "bestaudio", True),
    ],
)
def test_stage3_quality_contract_uses_audio_only_and_transcodes_only_mp3(
    tmp_path, monkeypatch, audio_mode, expected_format, expect_postprocessor
):
    captured = {}
    final_suffix = ".mp3" if audio_mode == "mp3" else ".webm"
    final_path = tmp_path / f"Fixture [media123]{final_suffix}"

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            final_path.write_bytes(b"fixture")
            return {
                "id": "media123",
                "title": "Fixture",
                "webpage_url": "https://youtu.be/media123",
                "filepath": str(final_path),
            }

        def prepare_filename(self, info):
            return str(tmp_path / "Fixture [media123].webm")

    monkeypatch.setattr(downloader_module, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(DownloadEngine, "ffmpeg_location", staticmethod(lambda: str(tmp_path)))
    monkeypatch.setattr(
        DownloadEngine,
        "_probe_audio",
        lambda self, path: AudioProbe("mp3" if audio_mode == "mp3" else "webm", "mp3" if audio_mode == "mp3" else "opus", 200.0, Path(path).stat().st_size),
    )
    monkeypatch.setattr(downloader_module, "apply_audio_tags", lambda *args, **kwargs: "")

    result = DownloadEngine().download(
        TrackRequest(index=1, query="Fixture", direct_url="https://youtu.be/media123"),
        output_dir=str(tmp_path),
        audio_mode=audio_mode,
    )

    assert captured["format"] == expected_format
    assert ("postprocessors" in captured) is expect_postprocessor
    assert result.verified is True
    assert result.final_path == str(final_path.resolve())


def test_stage3_metadata_tagging_is_best_effort(tmp_path, monkeypatch):
    target = tmp_path / "song.mp3"
    target.write_bytes(b"audio")
    saved = {"called": False}

    class FakeAudio(dict):
        def save(self):
            saved["called"] = True

    fake_audio = FakeAudio()
    fake_mutagen = SimpleNamespace(File=lambda *args, **kwargs: fake_audio)
    monkeypatch.setitem(__import__("sys").modules, "mutagen", fake_mutagen)

    track = TrackRequest(
        index=1,
        query="Artist - Song",
        title="Song",
        artist="Artist",
        metadata={"album": "Album", "track_number": 4, "year": 2026},
    )
    warning = apply_audio_tags(str(target), track)

    assert warning == ""
    assert fake_audio["title"] == ["Song"]
    assert fake_audio["artist"] == ["Artist"]
    assert fake_audio["album"] == ["Album"]
    assert fake_audio["tracknumber"] == ["4"]
    assert fake_audio["date"] == ["2026"]
    assert saved["called"] is True
