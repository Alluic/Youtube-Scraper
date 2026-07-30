import json

from youtube_digest.digest import pack_html_lines, render_digest_messages


def sample_summary() -> dict:
    return {
        "creator_thesis": "Falling inflation may support duration assets.",
        "creator_actions": ["Watch long-duration Treasury yields."],
        "investor_implications": ["A sustained disinflation trend may favor bonds."],
        "assets": [
            {
                "name": "US Treasury",
                "ticker": "TLT",
                "asset_class": "bond ETF",
                "direction": "bullish",
            }
        ],
        "why_chains": [
            {
                "driver": "Lower inflation",
                "mechanism": "lower expected policy rates",
                "affected_asset": "long-duration bonds",
                "action": "monitor duration exposure",
            }
        ],
        "evidence": [{"claim": "CPI slowed.", "timestamp_seconds": 125}],
        "catalysts": ["Next CPI release"],
        "time_horizon": "1-3 months",
        "risks": ["Inflation reacceleration"],
        "counterarguments": ["Term premium can rise independently."],
        "invalidation_conditions": ["Three-month inflation trend reverses."],
        "confidence": 0.82,
    }


def test_digest_is_escaped_timestamped_and_bounded() -> None:
    row = {
        "video_id": "abc",
        "title": "Rates < Inflation",
        "channel_title": "Macro & Markets",
        "url": "https://www.youtube.com/watch?v=abc",
        "published_at": "2026-07-30T12:00:00+00:00",
        "duration_seconds": 900,
        "transcript_source": "manual_captions",
        "summary_json": json.dumps(sample_summary()),
    }
    synthesis = {
        "dominant_themes": ["Disinflation"],
        "agreements": [],
        "disagreements": [],
        "repeated_assets": ["TLT"],
        "watch_items": ["CPI"],
    }

    messages = render_digest_messages(synthesis, [row])

    assert messages
    assert all(len(message) < 3900 for message in messages)
    combined = "\n".join(messages)
    assert "Rates &lt; Inflation" in combined
    assert "t=125s" in combined
    assert "WHY" in combined
    assert "TLT (US Treasury)" in combined
    assert "2026-07-30T12:00:00+00:00" in combined


def test_pack_splits_large_payloads() -> None:
    messages = pack_html_lines(["x" * 800 for _ in range(10)], max_chars=1000)

    assert len(messages) > 1
    assert all(len(message) < 1100 for message in messages)
