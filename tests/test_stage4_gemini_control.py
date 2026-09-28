from __future__ import annotations

from urllib.error import URLError

import app.services.downloader as downloader_module
from app.models import TrackRequest
from app.services.downloader import DownloadEngine
from app.services.gemini_agent import (
    CandidateChoice,
    CommandIntent,
    CommandPlan,
    GeminiAgent,
    GeminiResult,
)
from app.services.matcher import Candidate, score_candidate


def test_stage4_command_plan_rejects_unhashable_quality_shape(monkeypatch):
    agent = GeminiAgent(["fixture-key"])
    monkeypatch.setattr(
        agent,
        "_generate_json",
        lambda *args, **kwargs: GeminiResult(
            {
                "intent": "add_and_download",
                "scope": "add_and_download",
                "queries": ["Artist - Song"],
                "quality": ["mp3"],
                "avoid": ["live"],
                "prefer": [],
                "target_job_ids": [],
                "note": "fixture",
            }
        ),
    )

    result = agent.parse_command("tambahkan Artist - Song")

    assert result.data is None
    assert "quality" in result.error


def test_stage4_command_plan_is_typed_and_normalizes_versions(monkeypatch):
    agent = GeminiAgent(["fixture-key"])
    monkeypatch.setattr(
        agent,
        "_generate_json",
        lambda *args, **kwargs: GeminiResult(
            {
                "intent": "add_only",
                "scope": "add_only",
                "queries": ["Artist - Song"],
                "quality": "original",
                "avoid": ["sped-up", "live"],
                "prefer": ["acoustic"],
                "target_job_ids": [],
                "note": "Tambahkan saja",
            }
        ),
    )

    result = agent.parse_command("tambahkan Artist - Song, jangan live")

    assert isinstance(result.data, CommandPlan)
    assert result.data.intent is CommandIntent.ADD_ONLY
    assert result.data.queries == ("Artist - Song",)
    assert result.data.avoid_versions == ("sped up", "live")
    assert result.data.prefer_versions == ("acoustic",)


def test_stage4_unknown_intent_with_queries_is_rejected_before_mutation(monkeypatch):
    agent = GeminiAgent(["fixture-key"])
    monkeypatch.setattr(
        agent,
        "_generate_json",
        lambda *args, **kwargs: GeminiResult(
            {
                "intent": "unknown",
                "scope": "unknown",
                "queries": ["Invented Song"],
                "quality": None,
                "avoid": [],
                "prefer": [],
                "target_job_ids": [],
                "note": "fixture",
            }
        ),
    )

    result = agent.parse_command("lakukan sesuatu yang tidak didukung")

    assert result.data is None
    assert "unknown" in result.error.lower()


def test_stage4_live_chart_request_cannot_use_model_invented_queries(monkeypatch):
    agent = GeminiAgent(["fixture-key"])
    monkeypatch.setattr(
        agent,
        "_generate_json",
        lambda *args, **kwargs: GeminiResult(
            {
                "intent": "add_and_download",
                "scope": "add_and_download",
                "queries": ["Invented Artist - Invented Song"],
                "quality": "original",
                "avoid": [],
                "prefer": [],
                "target_job_ids": [],
                "note": "100 lagu terbaru",
            }
        ),
    )

    result = agent.parse_command("download top 100 lagu terbaru sekarang")

    assert isinstance(result.data, CommandPlan)
    assert result.data.intent is CommandIntent.UNKNOWN
    assert result.data.queries == ()
    assert "URL playlist" in result.data.note


def test_stage4_candidate_choice_rejects_bool_index():
    try:
        CandidateChoice.from_payload({"index": True, "confidence": 0.99, "reason": "fixture"}, 2)
    except ValueError as exc:
        assert "index" in str(exc)
    else:
        raise AssertionError("bool index harus ditolak")


def test_stage4_low_confidence_candidate_still_requires_review(monkeypatch):
    agent = GeminiAgent(["fixture-key"])
    monkeypatch.setattr(
        agent,
        "_generate_json",
        lambda *args, **kwargs: GeminiResult({"index": 0, "confidence": 0.40, "reason": "ragu"}),
    )
    candidates = [Candidate(url="a", title="Artist - Song", uploader="Artist", score=0.9)]

    assert agent.choose_candidate("Artist - Song", candidates) is None


def test_stage4_one_operation_never_sweeps_100_failed_keys(monkeypatch):
    keys = [f"fixture-key-{index:03d}" for index in range(100)]
    agent = GeminiAgent(keys)
    calls: list[str] = []

    def fail(api_key, prompt, **kwargs):
        calls.append(api_key)
        raise URLError(f"network failed for {api_key}")

    monkeypatch.setattr(agent, "_request_text", fail)

    result = agent._generate_json("fixture")

    assert result.data is None
    assert len(calls) == 3
    assert all(key not in result.error for key in keys)


def test_stage4_without_key_does_not_attempt_network(monkeypatch):
    agent = GeminiAgent([])
    called = {"value": False}

    def unexpected(*args, **kwargs):
        called["value"] = True
        raise AssertionError("network tidak boleh dipanggil")

    monkeypatch.setattr(agent, "_request_text", unexpected)
    result = agent._generate_json("fixture")

    assert result.data is None
    assert called["value"] is False


def test_stage4_parse_cache_avoids_duplicate_model_request(monkeypatch):
    agent = GeminiAgent(["fixture-key"])
    calls = {"count": 0}

    def fake_generate(*args, **kwargs):
        calls["count"] += 1
        return GeminiResult(
            {
                "intent": "download_queue",
                "scope": "download_queue",
                "queries": [],
                "quality": None,
                "avoid": ["live"],
                "prefer": [],
                "target_job_ids": [],
                "note": "download",
            }
        )

    monkeypatch.setattr(agent, "_generate_json", fake_generate)

    first = agent.parse_command("download antrean jangan live")
    second = agent.parse_command("download antrean jangan live")

    assert isinstance(first.data, CommandPlan)
    assert second.data == first.data
    assert calls["count"] == 1


def test_stage4_model_discovery_keeps_only_generate_content_models(monkeypatch):
    agent = GeminiAgent(["fixture-key"])
    monkeypatch.setattr(
        agent,
        "_request_models",
        lambda *args, **kwargs: {
            "models": [
                {"name": "models/gemini-fixture", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embed-fixture", "supportedGenerationMethods": ["embedContent"]},
                {"name": "models/gemini-second", "supportedGenerationMethods": ["countTokens", "generateContent"]},
            ]
        },
    )

    result = agent.list_models()

    assert result.error == ""
    assert result.models == ("gemini-fixture", "gemini-second")


def test_stage4_avoid_version_has_strong_matching_effect():
    candidate = Candidate(
        url="a",
        title="Artist - Song Live",
        uploader="Artist",
        duration=200,
    )
    normal_score = score_candidate("Artist - Song", candidate, 200)
    avoided_score = score_candidate("Artist - Song", candidate, 200, avoid_versions={"live"})

    assert avoided_score <= normal_score - 0.55


def test_stage4_prefer_version_is_allowed_and_rewarded():
    candidate = Candidate(
        url="a",
        title="Artist - Song Acoustic",
        uploader="Artist",
        duration=200,
    )
    normal_score = score_candidate("Artist - Song", candidate, 200)
    preferred_score = score_candidate("Artist - Song", candidate, 200, prefer_versions={"acoustic"})

    assert preferred_score > normal_score


def test_stage4_downloader_passes_job_preferences_to_search_and_gemini(monkeypatch):
    captured = {}
    candidate = Candidate(
        url="https://youtu.be/fixture",
        title="Artist - Song",
        uploader="Artist",
        duration=200,
        score=0.90,
    )

    def fake_search(*args, **kwargs):
        captured["avoid"] = kwargs.get("avoid_versions")
        captured["prefer"] = kwargs.get("prefer_versions")
        return [candidate]

    monkeypatch.setattr(downloader_module, "search_youtube", fake_search)
    track = TrackRequest(
        index=1,
        query="Artist - Song",
        duration=200,
        metadata={"avoid_versions": ["live", "remix"], "prefer_versions": ["acoustic"]},
    )

    chosen = DownloadEngine().resolve_candidate(track)

    assert chosen is candidate
    assert captured["avoid"] == {"live", "remix"}
    assert captured["prefer"] == {"acoustic"}
