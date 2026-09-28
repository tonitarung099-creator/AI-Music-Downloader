from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication

import app.services.downloader as downloader_module
import app.workers as workers_module
from app.config import AppConfig
from app.models import TrackRequest, TrackStatus
from app.services.downloader import DownloadCancelled, DownloadEngine
from app.services.errors import ErrorKind, classify_exception
from app.services.gemini_agent import GeminiAgent
from app.services.identity import canonical_media_key, track_dedup_key
from app.storage import QueueRepository
from app.workers import QueueWorker


def _repo(tmp_path: Path) -> QueueRepository:
    return QueueRepository(tmp_path / "data" / "queue.sqlite3")


def test_stage2_restores_100_jobs_and_marks_runtime_states_interrupted(tmp_path):
    repo = _repo(tmp_path)
    tracks = [TrackRequest(index=i + 1, query=f"Artist {i} - Song {i}") for i in range(100)]
    result = repo.add_tracks(tracks)
    assert len(result.added) == 100
    assert result.duplicates == []

    runtime_states = [
        TrackStatus.SEARCHING,
        TrackStatus.DOWNLOADING,
        TrackStatus.PAUSED,
        TrackStatus.RETRY_WAIT,
    ]
    for track, status in zip(tracks[:4], runtime_states):
        track.status = status
        track.progress = 37.0
        repo.checkpoint(track, event="fixture_runtime")

    restored = QueueRepository(repo.path).restore_queue()

    assert len(restored) == 100
    assert [track.job_id for track in restored] == [track.job_id for track in tracks]
    assert all(track.status == TrackStatus.INTERRUPTED for track in restored[:4])
    assert all(track.status == TrackStatus.QUEUED for track in restored[4:])


def test_stage2_restore_preserves_resolved_candidate_choice(tmp_path):
    repo = _repo(tmp_path)
    track = TrackRequest(index=1, query="Artist - Song")
    repo.add_tracks([track])
    track.resolved_url = "https://www.youtube.com/watch?v=chosen123"
    track.resolved_title = "Artist - Song (Official Audio)"
    track.metadata["match_score"] = 0.92
    track.status = TrackStatus.SEARCHING
    repo.checkpoint(track, event="candidate_selected")

    restored = QueueRepository(repo.path).restore_queue()

    assert len(restored) == 1
    assert restored[0].status == TrackStatus.INTERRUPTED
    assert restored[0].resolved_url == track.resolved_url
    assert restored[0].resolved_title == track.resolved_title
    assert restored[0].metadata["match_score"] == 0.92


def test_stage2_youtube_tracking_params_dedup_to_same_media(tmp_path):
    repo = _repo(tmp_path)
    first = TrackRequest(
        index=1,
        query="Video A",
        source="youtube",
        direct_url="https://www.youtube.com/watch?v=abc123&si=tracking",
    )
    second = TrackRequest(
        index=2,
        query="Video A copy",
        source="youtube",
        direct_url="https://youtu.be/abc123?feature=share",
    )

    added = repo.add_tracks([first])
    duplicate = repo.add_tracks([second])

    assert len(added.added) == 1
    assert duplicate.added == []
    assert len(duplicate.duplicates) == 1
    assert canonical_media_key(first.direct_url or "") == "youtube:video:abc123"
    assert track_dedup_key(first) == track_dedup_key(second)


def test_stage2_query_dedup_keeps_live_and_plain_versions_distinct(tmp_path):
    repo = _repo(tmp_path)
    plain = TrackRequest(index=1, query="Artist - Song")
    live = TrackRequest(index=2, query="Artist - Song Live")

    result = repo.add_tracks([plain, live])

    assert len(result.added) == 2
    assert track_dedup_key(plain) != track_dedup_key(live)


def test_stage2_completed_manifest_prevents_redownload_after_queue_removal(tmp_path):
    repo = _repo(tmp_path)
    original = TrackRequest(
        index=1,
        query="Finished",
        source="youtube",
        direct_url="https://www.youtube.com/watch?v=done123",
    )
    repo.add_tracks([original])
    original.status = TrackStatus.DONE
    original.output_path = str(tmp_path / "Finished [done123].m4a")
    repo.checkpoint(original, event="completed")
    repo.remove_jobs({original.job_id})

    repeated = TrackRequest(
        index=1,
        query="Finished again",
        source="youtube",
        direct_url="https://youtu.be/done123",
    )
    result = repo.add_tracks([repeated])

    assert result.added == []
    assert len(result.duplicates) == 1
    assert result.duplicates[0].status == TrackStatus.DONE.value
    assert repo.manifest_entry(track_dedup_key(original)) is not None


def test_stage2_restored_done_job_is_never_downloaded_again(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    repo = _repo(tmp_path)
    done = TrackRequest(index=1, query="Already done", status=TrackStatus.DONE, progress=100.0)
    repo.add_tracks([done])
    repo.checkpoint(done, event="completed")
    restored = QueueRepository(repo.path).restore_queue()

    worker = QueueWorker(
        restored,
        AppConfig(output_dir=str(tmp_path), max_retries=3),
        GeminiAgent([]),
        repository=repo,
    )

    class MustNotRunEngine:
        def download(self, *args, **kwargs):
            raise AssertionError("DONE job must not be downloaded again")

    worker.engine = MustNotRunEngine()
    worker.run()

    assert restored[0].status == TrackStatus.DONE
    assert restored[0].attempt_count == 0


def test_stage2_reorder_changes_position_not_identity(tmp_path):
    repo = _repo(tmp_path)
    tracks = [TrackRequest(index=i + 1, query=f"Song {i}") for i in range(3)]
    repo.add_tracks(tracks)
    reversed_ids = [track.job_id for track in reversed(tracks)]

    repo.reorder(reversed_ids)
    restored = QueueRepository(repo.path).restore_queue()

    assert [track.job_id for track in restored] == reversed_ids
    assert [track.index for track in restored] == [1, 2, 3]


def test_stage2_retry_scope_does_not_run_unrelated_queued_job(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    repo = _repo(tmp_path)
    target = TrackRequest(index=1, query="Target", status=TrackStatus.QUEUED)
    unrelated = TrackRequest(index=2, query="Unrelated", status=TrackStatus.QUEUED)
    repo.add_tracks([target, unrelated])

    worker = QueueWorker(
        [target],
        AppConfig(output_dir=str(tmp_path), max_retries=0),
        GeminiAgent([]),
        repository=repo,
    )

    class FixtureEngine:
        def download(self, track, **kwargs):
            return {"id": track.job_id}

    worker.engine = FixtureEngine()
    worker.run()

    restored = QueueRepository(repo.path).restore_queue()
    by_id = {track.job_id: track for track in restored}
    assert by_id[target.job_id].status == TrackStatus.DONE
    assert by_id[unrelated.job_id].status == TrackStatus.QUEUED
    assert by_id[unrelated.job_id].attempt_count == 0


def test_stage2_stop_cancels_current_job_but_leaves_unstarted_job_queued(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    repo = _repo(tmp_path)
    current = TrackRequest(index=1, query="Current")
    later = TrackRequest(index=2, query="Later")
    repo.add_tracks([current, later])

    worker = QueueWorker(
        [current, later],
        AppConfig(output_dir=str(tmp_path), max_retries=2),
        GeminiAgent([]),
        repository=repo,
    )

    class StopOnFirstEngine:
        def download(self, track, **kwargs):
            kwargs["stop_event"].set()
            raise DownloadCancelled("Dibatalkan pengguna.")

    worker.engine = StopOnFirstEngine()
    worker.run()

    restored = QueueRepository(repo.path).restore_queue()
    by_id = {track.job_id: track for track in restored}
    assert by_id[current.job_id].status == TrackStatus.CANCELLED
    assert by_id[later.job_id].status == TrackStatus.QUEUED
    assert by_id[later.job_id].attempt_count == 0


def test_stage2_permanent_error_fails_fast_without_auto_retry(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    track = TrackRequest(index=1, query="Broken URL")
    worker = QueueWorker(
        [track],
        AppConfig(output_dir=str(tmp_path), max_retries=5),
        GeminiAgent([]),
    )

    class PermanentFailureEngine:
        def __init__(self):
            self.calls = 0

        def download(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("Unsupported URL: fixture")

    engine = PermanentFailureEngine()
    worker.engine = engine
    worker.run()

    assert engine.calls == 1
    assert track.status == TrackStatus.FAILED
    assert track.error_retryable is False
    assert track.error_code == ErrorKind.INVALID_INPUT.value


def test_stage2_transient_error_retries_only_with_backoff_budget(tmp_path, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    monkeypatch.setattr(workers_module, "retry_delay_seconds", lambda *args, **kwargs: 0.0)
    track = TrackRequest(index=1, query="Temporary network")
    worker = QueueWorker(
        [track],
        AppConfig(output_dir=str(tmp_path), max_retries=3),
        GeminiAgent([]),
    )

    class TransientEngine:
        def __init__(self):
            self.calls = 0

        def download(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("timed out")
            return {"id": "ok"}

    engine = TransientEngine()
    worker.engine = engine
    worker.run()

    assert engine.calls == 2
    assert track.status == TrackStatus.DONE
    assert track.attempt_count == 2


def test_stage2_error_taxonomy_is_conservative():
    permanent = classify_exception(RuntimeError("Video unavailable"))
    transient = classify_exception(TimeoutError("timed out"))
    unknown = classify_exception(RuntimeError("mystery failure"))

    assert permanent.retryable is False
    assert transient.retryable is True
    assert unknown.retryable is False


def test_stage2_output_template_is_not_based_on_queue_index(tmp_path, monkeypatch):
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            return {"id": "media123", "title": "Fixture"}

        def prepare_filename(self, info):
            return str(tmp_path / "Fixture [media123].webm")

    monkeypatch.setattr(downloader_module, "YoutubeDL", FakeYoutubeDL)
    engine = DownloadEngine()
    track = TrackRequest(
        index=999,
        query="Fixture",
        direct_url="https://www.youtube.com/watch?v=media123",
    )

    engine.download(track, output_dir=str(tmp_path), audio_mode="original")

    assert "999" not in captured["outtmpl"]
    assert "%(id)s" in captured["outtmpl"]
