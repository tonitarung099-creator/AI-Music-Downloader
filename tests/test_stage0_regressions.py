from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

import app.config as config_module
import app.services.downloader as downloader_module
import app.services.spotify as spotify_module
from app.config import AppConfig
from app.models import TrackRequest, TrackStatus
from app.services.downloader import DownloadEngine
from app.services.gemini_agent import GeminiAgent, GeminiResult
from app.services.matcher import Candidate
from app.services.spotify import SpotifyResolverError
from app.workers import ImportWorker, QueueWorker


KNOWN_STAGE0 = pytest.mark.xfail(strict=True)


def test_f01_spotify_resolver_bootstraps_client_before_metadata(monkeypatch):
    state = {"initialized": False, "init_calls": 0}

    class FakeSpotifyClient:
        @classmethod
        def init(cls, *args, **kwargs):
            state["initialized"] = True
            state["init_calls"] += 1

        def __new__(cls, *args, **kwargs):
            if not state["initialized"]:
                raise RuntimeError("SpotifyClient belum diinisialisasi")
            return super().__new__(cls)

    class FakePlaylist:
        @staticmethod
        def get_metadata(url):
            FakeSpotifyClient()
            song = SimpleNamespace(
                name="Fixture Song",
                artists=["Fixture Artist"],
                artist="Fixture Artist",
                duration=201,
            )
            return SimpleNamespace(name="Fixture Playlist"), [song]

    backend = spotify_module._SpotdlBackend(
        Album=object,
        Playlist=FakePlaylist,
        Song=object,
        SpotifyClient=FakeSpotifyClient,
        SpotifyError=RuntimeError,
        default_config={"client_id": "fixture", "client_secret": "fixture"},
    )
    monkeypatch.setattr(spotify_module, "_load_spotdl_backend", lambda: backend)

    tracks = spotify_module.resolve_spotify("https://open.spotify.com/playlist/stage0", timeout=1)

    assert state["init_calls"] == 1
    assert [track.query for track in tracks] == ["Fixture Artist - Fixture Song"]


@KNOWN_STAGE0(reason="F03: kandidat sangat buruk masih diterima bila hanya satu kandidat")
def test_f03_negative_score_candidate_is_not_silently_accepted(monkeypatch):
    bad = Candidate(
        url="https://www.youtube.com/watch?v=wrong",
        title="Completely Different Song",
        uploader="Unknown Channel",
        duration=999,
        score=-0.8,
    )
    monkeypatch.setattr(downloader_module, "search_youtube", lambda *args, **kwargs: [bad])

    engine = DownloadEngine()
    track = TrackRequest(index=1, query="Requested Artist - Requested Song")

    with pytest.raises(RuntimeError):
        engine.resolve_candidate(track)


@KNOWN_STAGE0(reason="F03: confidence Gemini 0.0 masih dapat memilih kandidat")
def test_f03_gemini_rejects_zero_confidence_choice(monkeypatch):
    agent = GeminiAgent(["fixture-key"])
    monkeypatch.setattr(
        agent,
        "_generate_json",
        lambda prompt, **kwargs: GeminiResult({"index": 0, "confidence": 0.0, "reason": "tidak yakin"}),
    )
    candidates = [
        Candidate(
            url="https://www.youtube.com/watch?v=fixture",
            title="Fixture Candidate",
            uploader="Fixture Channel",
            score=0.6,
        )
    ]

    assert agent.choose_candidate("Requested Artist - Requested Song", candidates) is None


def test_f05_import_preserves_valid_rows_when_later_spotify_row_fails(monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    def fail_spotify(url, **kwargs):
        raise SpotifyResolverError("fixture gagal")

    monkeypatch.setattr("app.workers.resolve_spotify", fail_spotify)

    worker = ImportWorker(
        "Artist A - Song A\n"
        "https://open.spotify.com/track/broken\n"
        "Artist B - Song B",
        start_index=1,
    )
    captured_tracks = []
    captured_errors = []
    worker.tracks_ready.connect(lambda tracks: captured_tracks.extend(tracks))
    worker.failed.connect(captured_errors.append)

    worker.run()

    assert [track.query for track in captured_tracks] == [
        "Artist A - Song A",
        "Artist B - Song B",
    ]
    assert captured_errors


def test_f08_null_config_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "app_root", lambda: tmp_path)
    (tmp_path / "config.json").write_text("null", encoding="utf-8")

    cfg = AppConfig.load()

    assert isinstance(cfg, AppConfig)
    assert cfg.audio_mode == "original"
    assert cfg.max_retries == 2


@KNOWN_STAGE0(reason="F10: hasil Gemini belum divalidasi sebagai CommandPlan sebelum dipakai UI")
def test_f10_parse_command_rejects_invalid_quality_shape(monkeypatch):
    agent = GeminiAgent(["fixture-key"])
    monkeypatch.setattr(
        agent,
        "_generate_json",
        lambda prompt, **kwargs: GeminiResult(
            {
                "intent": "add_and_download",
                "queries": ["Artist - Song"],
                "quality": ["mp3"],
                "avoid": ["live"],
            }
        ),
    )

    result = agent.parse_command("tambahkan Artist - Song")

    assert result.data is None
    assert result.error


@KNOWN_STAGE0(reason="F12: QueueWorker menandai DONE walau downloader tidak menghasilkan file/result valid")
def test_f12_empty_download_result_must_not_be_marked_done(tmp_path):
    track = TrackRequest(
        index=1,
        query="Fixture direct URL",
        source="url",
        direct_url="https://example.invalid/audio",
    )
    config = AppConfig(output_dir=str(tmp_path), max_retries=0)
    worker = QueueWorker([track], config, GeminiAgent([]))

    class EmptyResultEngine:
        def download(self, *args, **kwargs):
            return {}

    worker.engine = EmptyResultEngine()
    worker.run()

    assert track.status is not TrackStatus.DONE
