from app.services.spotify import _extract_json_payload, _to_track


def test_extract_spotdl_json_with_log_prefix():
    payload = _extract_json_payload('log line\n[{"name":"Song","artists":["Artist"],"duration":201000}]')
    assert isinstance(payload, list)
    assert payload[0]["name"] == "Song"


def test_spotify_track_converts_milliseconds_and_builds_query():
    track = _to_track({"name": "Song", "artists": ["Artist", "Guest"], "duration": 201000})
    assert track is not None
    assert track.query == "Artist, Guest - Song"
    assert track.duration == 201.0
