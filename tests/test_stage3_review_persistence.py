from __future__ import annotations

from app.models import TrackRequest, TrackStatus
from app.storage import QueueRepository


def test_stage3_needs_review_candidates_survive_restart(tmp_path):
    repo = QueueRepository(tmp_path / "queue.sqlite3")
    track = TrackRequest(index=1, query="Artist - Song")
    repo.add_tracks([track])

    track.status = TrackStatus.NEEDS_REVIEW
    track.metadata["match_state"] = "NEEDS_REVIEW"
    track.metadata["review_candidates"] = [
        {
            "url": "https://www.youtube.com/watch?v=choice1",
            "title": "Artist - Song",
            "uploader": "Artist",
            "duration": 200,
            "score": 0.73,
            "versions": [],
        }
    ]
    repo.checkpoint(track, event="needs_review")

    restored = QueueRepository(repo.path).restore_queue()

    assert len(restored) == 1
    assert restored[0].status == TrackStatus.NEEDS_REVIEW
    assert restored[0].metadata["match_state"] == "NEEDS_REVIEW"
    assert restored[0].metadata["review_candidates"][0]["url"].endswith("choice1")
