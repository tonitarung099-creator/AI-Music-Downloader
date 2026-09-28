from __future__ import annotations

import json
import zipfile

import app.config as config_module
from app.config import AppConfig
from app.models import TrackRequest, TrackStatus
from app.services.diagnostics import DiagnosticLog, redact_text, write_diagnostic_bundle
from app.services.reports import export_batch_csv, export_batch_json
from app.ui.stage5 import Stage5UiMixin


SECRET = "AIzaSyStage5FixtureSecret1234567890"


def test_stage5_redaction_removes_keys_tokens_and_bearer():
    text = (
        f"api_key={SECRET} https://example.test/?token=very-secret-token-12345 "
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456"
    )
    cleaned = redact_text(text)
    assert SECRET not in cleaned
    assert "very-secret-token-12345" not in cleaned
    assert "abcdefghijklmnopqrstuvwxyz123456" not in cleaned
    assert "<rahasia>" in cleaned


def test_stage5_reports_never_export_secret_metadata(tmp_path):
    track = TrackRequest(
        index=1,
        query="Artist - Song",
        status=TrackStatus.DONE,
        resolved_title="Artist - Song",
        metadata={
            "verified_container": "m4a",
            "verified_audio_codec": "aac",
            "api_key": SECRET,
            "match_reason": f"matched; token={SECRET}",
        },
    )
    csv_path = export_batch_csv(tmp_path / "report.csv", [track])
    json_path = export_batch_json(tmp_path / "report.json", [track])
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    json_text = json_path.read_text(encoding="utf-8")
    assert SECRET not in csv_text
    assert SECRET not in json_text
    assert "m4a" in csv_text
    assert "aac" in json_text


def test_stage5_diagnostic_bundle_is_redacted(tmp_path):
    cfg = AppConfig(
        output_dir=str(tmp_path / "downloads"),
        gemini_api_keys=[SECRET],
        gemini_key_storage="session",
    )
    log = DiagnosticLog()
    log.append(f"Gemini error key={SECRET}")
    track = TrackRequest(index=1, query=f"Song?token={SECRET}", metadata={"secret": SECRET})
    bundle = write_diagnostic_bundle(
        tmp_path / "diagnostics.zip",
        log=log,
        config=cfg,
        tracks=[track],
        tool_status={"message": f"Bearer {SECRET}"},
    )
    with zipfile.ZipFile(bundle) as archive:
        combined = b"\n".join(archive.read(name) for name in archive.namelist()).decode("utf-8")
    assert SECRET not in combined
    assert "gemini_key_count" in combined
    assert "<rahasia>" in combined


def test_stage5_dpapi_mode_removes_plaintext_from_config(tmp_path, monkeypatch):
    class FakeStore:
        saved: list[str] = []
        available = True

        def __init__(self, root=None):
            self.root = root

        def save(self, keys):
            FakeStore.saved = list(keys)

        def load(self):
            return list(FakeStore.saved)

        def delete(self):
            FakeStore.saved = []

    monkeypatch.setattr(config_module, "app_root", lambda: tmp_path)
    monkeypatch.setattr(config_module, "WindowsDpapiKeyStore", FakeStore)
    cfg = AppConfig(
        output_dir=str(tmp_path / "downloads"),
        gemini_api_keys=[SECRET, SECRET],
        gemini_key_storage="windows_dpapi",
    )

    cfg.save()

    raw = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert raw["gemini_api_keys"] == []
    assert raw["gemini_key_storage"] == "windows_dpapi"
    assert FakeStore.saved == [SECRET]
    loaded = AppConfig.load()
    assert loaded.gemini_api_keys == [SECRET]


def test_stage5_session_mode_does_not_write_api_key_to_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "app_root", lambda: tmp_path)
    cfg = AppConfig(
        output_dir=str(tmp_path / "downloads"),
        gemini_api_keys=[SECRET],
        gemini_key_storage="session",
    )
    cfg.save()
    text = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert SECRET not in text
    assert json.loads(text)["gemini_api_keys"] == []


def test_stage5_drop_txt_and_csv_preserves_input_order(tmp_path):
    txt = tmp_path / "songs.txt"
    txt.write_text("Artist A - Song A\nArtist B - Song B\n", encoding="utf-8")
    csv_path = tmp_path / "songs.csv"
    csv_path.write_text("artis,judul\nArtist C,Song C\nhttps://example.test/song\n", encoding="utf-8")

    assert Stage5UiMixin._read_drop_file(txt) == ["Artist A - Song A", "Artist B - Song B"]
    assert Stage5UiMixin._read_drop_file(csv_path) == ["Artist C - Song C", "https://example.test/song"]


def test_stage5_status_filter_scope_preserves_stable_job_order():
    first = TrackRequest(index=1, query="Alpha Artist - Alpha Song")
    second = TrackRequest(index=2, query="Beta Artist - Beta Song", status=TrackStatus.DONE)
    third = TrackRequest(index=3, query="Gamma Artist - Gamma Song", status=TrackStatus.NEEDS_REVIEW)
    tracks = [first, second, third]
    original_ids = [track.job_id for track in tracks]

    done_ids = [
        track.job_id
        for track in tracks
        if Stage5UiMixin._status_matches(track, "done")
    ]
    review_ids = [
        track.job_id
        for track in tracks
        if Stage5UiMixin._status_matches(track, "review")
    ]
    beta_ids = [
        track.job_id
        for track in tracks
        if "beta" in " ".join(
            str(value or "")
            for value in (
                track.display_name,
                track.query,
                track.source,
                track.resolved_title,
                track.resolved_url,
            )
        ).casefold()
    ]

    assert done_ids == [second.job_id]
    assert review_ids == [third.job_id]
    assert beta_ids == [second.job_id]
    assert [track.job_id for track in tracks] == original_ids
