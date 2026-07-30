from youtube_digest.transcripts import format_timestamp, normalize_vtt


def test_vtt_normalization_and_deduplication() -> None:
    source = """WEBVTT

00:00:01.000 --> 00:00:03.000
<c>Inflation is falling.</c>

00:00:03.000 --> 00:00:05.000
Inflation is falling.

00:01:05.000 --> 00:01:07.000
Watch <b>bond yields</b>.
"""

    normalized = normalize_vtt(source)

    assert normalized.count("Inflation is falling.") == 1
    assert "[00:01:05] Watch bond yields." in normalized


def test_timestamp_format() -> None:
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(3723) == "01:02:03"
