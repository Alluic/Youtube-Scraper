from youtube_digest.youtube import parse_iso8601_duration, parse_youtube_datetime


def test_duration_parser() -> None:
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_iso8601_duration("PT12M") == 720
    assert parse_iso8601_duration(None) is None


def test_youtube_datetime_is_utc() -> None:
    parsed = parse_youtube_datetime("2026-07-30T12:00:00Z")

    assert parsed.isoformat() == "2026-07-30T12:00:00+00:00"
