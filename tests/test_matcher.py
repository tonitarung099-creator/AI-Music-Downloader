from app.services.matcher import Candidate, normalize, score_candidate


def test_normalize_removes_noise_and_accents():
    assert normalize("Beyoncé - Halo (Official Music Video)") == "beyonce halo"


def test_original_beats_unrequested_live_version():
    query = "Adele - Hello"
    original = Candidate(url="x", title="Adele - Hello (Official Audio)", uploader="Adele")
    live = Candidate(url="y", title="Adele - Hello Live at Wembley", uploader="Fan Channel")
    assert score_candidate(query, original) > score_candidate(query, live)


def test_requested_remix_is_not_penalized_as_variant():
    query = "Artist - Song remix"
    remix = Candidate(url="x", title="Artist - Song Remix", uploader="Artist - Topic")
    plain = Candidate(url="y", title="Artist - Song", uploader="Random")
    assert score_candidate(query, remix) >= score_candidate(query, plain)


def test_duration_bonus_prefers_closer_track():
    query = "Artist - Song"
    close = Candidate(url="x", title="Artist - Song", uploader="Artist", duration=201)
    far = Candidate(url="y", title="Artist - Song", uploader="Artist", duration=390)
    assert score_candidate(query, close, 200) > score_candidate(query, far, 200)
