from __future__ import annotations

import json

from PySide6.QtCore import QCoreApplication

import app.config as config_module
import app.workers as workers_module
from app.config import AppConfig
from app.controllers.lifecycle import OperationCoordinator
from app.models import TrackRequest
from app.services.downloader import DownloadResult
from app.services.gemini_agent import GeminiAgent
from app.workers import ImportWorker, QueueWorker, _is_spotify, _is_youtube_playlist


def test_url_routing_uses_real_hostname_and_playlist_query():
    assert _is_spotify("https://open.spotify.com/track/abc123") is True
    assert _is_spotify("https://example.org/?next=https://open.spotify.com/track/abc") is False
    assert _is_spotify("https://open.spotify.com.evil.example/track/abc") is False

    assert _is_youtube_playlist("https://www.youtube.com/playlist?list=PL123") is True
    assert _is_youtube_playlist("https://music.youtube.com/watch?v=abc&list=PL123") is True
    assert _is_youtube_playlist("https://youtu.be/abc?list=PL123") is True
    assert _is_youtube_playlist("https://example.org/?next=youtube.com/playlist?list=PL123") is False
    assert _is_youtube_playlist("https://www.youtube.com/watch?v=abc") is False


def test_manual_import_does_not_touch_spotify_backend(monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    def forbidden_spotify(*args, **kwargs):
        raise AssertionError("manual input must not call Spotify")

    monkeypatch.setattr(workers_module, "resolve_spotify", forbidden_spotify)
    worker = ImportWorker("Artist A - Song A\nArtist B - Song B")
    captured = []
    worker.tracks_ready.connect(lambda tracks: captured.extend(tracks))
    worker.run()

    assert [track.query for track in captured] == ["Artist A - Song A", "Artist B - Song B"]


def test_playlist_none_entry_is_skipped_without_losing_valid_entries(monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    monkeypatch.setattr(
        workers_module,
        "_youtube_playlist_entries",
        lambda url: [
            None,
            {"id": "ok123", "title": "Valid Song", "duration": 200},
        ],
    )

    worker = ImportWorker("https://www.youtube.com/playlist?list=PLfixture")
    captured = []
    errors = []
    worker.tracks_ready.connect(lambda tracks: captured.extend(tracks))
    worker.failed.connect(errors.append)
    worker.run()

    assert len(captured) == 1
    assert captured[0].title == "Valid Song"
    assert captured[0].direct_url == "https://www.youtube.com/watch?v=ok123"
    assert errors


def test_cancelled_import_emits_cancelled_result_without_processing():
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    worker = ImportWorker("Artist - Song")
    captured = []
    worker.result_ready.connect(captured.append)
    worker.cancel()
    worker.run()

    assert len(captured) == 1
    assert captured[0].cancelled is True
    assert captured[0].tracks == []


def test_config_wrong_types_are_sanitized(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "app_root", lambda: tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "output_dir": 123,
                "audio_mode": ["mp3"],
                "gemini_model": None,
                "gemini_api_keys": "not-a-list",
                "max_retries": "many",
            }
        ),
        encoding="utf-8",
    )

    cfg = AppConfig.load()

    assert cfg.output_dir == str((tmp_path / "downloads").resolve())
    assert cfg.audio_mode == "original"
    assert cfg.gemini_model == "gemini-3.8-flash"
    assert cfg.gemini_api_keys == []
    assert cfg.max_retries == 2


def test_config_runtime_wrong_types_are_sanitized_on_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "app_root", lambda: tmp_path)
    cfg = AppConfig()
    cfg.output_dir = 123  # type: ignore[assignment]
    cfg.audio_mode = ["mp3"]  # type: ignore[assignment]
    cfg.gemini_model = {"model": "bad"}  # type: ignore[assignment]
    cfg.gemini_api_keys = "not-a-list"  # type: ignore[assignment]
    cfg.max_retries = "many"  # type: ignore[assignment]

    snapshot = cfg.snapshot()

    assert snapshot.output_dir == str((tmp_path / "downloads").resolve())
    assert snapshot.audio_mode == "original"
    assert snapshot.gemini_model == "gemini-3.8-flash"
    assert snapshot.gemini_api_keys == []
    assert snapshot.max_retries == 2


def test_config_save_is_atomic_and_keeps_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "app_root", lambda: tmp_path)
    path = tmp_path / "config.json"
    path.write_text('{"audio_mode":"original","sentinel":1}', encoding="utf-8")

    cfg = AppConfig(output_dir=str(tmp_path / "downloads"), audio_mode="mp3")
    cfg.save()

    saved = json.loads(path.read_text(encoding="utf-8"))
    backup = json.loads((tmp_path / "config.json.bak").read_text(encoding="utf-8"))
    assert saved["audio_mode"] == "mp3"
    assert backup["sentinel"] == 1
    assert not list(tmp_path.glob(".config.json.*.tmp"))


def test_config_snapshot_detaches_mutable_key_list(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "app_root", lambda: tmp_path)
    cfg = AppConfig(gemini_api_keys=["a", "b"])
    snapshot = cfg.snapshot()

    cfg.gemini_api_keys.append("c")

    assert snapshot.gemini_api_keys == ["a", "b"]


def test_operation_coordinator_rejects_stale_import_and_agent_results():
    coordinator = OperationCoordinator()
    coordinator.begin_import("import-new")
    assert coordinator.is_current_import("import-old") is False
    assert coordinator.is_current_import("import-new") is True

    coordinator.invalidate_import()
    assert coordinator.is_current_import("import-new") is False

    coordinator.begin_agent("agent-new")
    assert coordinator.is_current_agent("agent-old") is False
    assert coordinator.is_current_agent("agent-new") is True


def test_queue_worker_progress_events_use_stable_job_id(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    track = TrackRequest(
        index=1,
        query="Fixture direct URL",
        source="url",
        direct_url="https://example.invalid/audio",
    )
    worker = QueueWorker(
        [track],
        AppConfig(output_dir=str(tmp_path), max_retries=0),
        GeminiAgent([]),
    )

    class FixtureEngine:
        def download(self, *args, **kwargs):
            callback = kwargs.get("progress_cb")
            if callback:
                callback(50.0, "fixture")
            path = tmp_path / "fixture.webm"
            path.write_bytes(b"fixture-audio")
            return DownloadResult(
                final_path=str(path),
                source_id="fixture",
                source_url="https://example.invalid/audio",
                title="Fixture",
                container="webm",
                audio_codec="opus",
                duration=1.0,
                size_bytes=path.stat().st_size,
                verified=True,
            )

    worker.engine = FixtureEngine()
    event_ids = []
    worker.item_changed.connect(lambda job_id, *_: event_ids.append(job_id))
    worker.run()

    assert event_ids
    assert set(event_ids) == {track.job_id}
