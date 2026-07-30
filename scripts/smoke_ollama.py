"""Credential-free local Ollama structured-output smoke test."""

from __future__ import annotations

import logging

from youtube_digest.ollama_client import OllamaClient


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("ollama-smoke")
    client = OllamaClient("http://127.0.0.1:11434", "gemma4:12b", logger)
    client.ensure_running()
    video = {
        "title": "Synthetic CPI and Treasury Market Update",
        "channel_title": "Fixture Research",
        "description": "A test discussion of inflation, policy rates, and bond duration.",
        "published_at": "2026-07-30T12:00:00+00:00",
    }
    classification = client.classify(video)
    assert "is_relevant" in classification
    transcript = "\n".join(
        [
            "[00:00:05] Headline CPI slowed from three point two to two point eight percent.",
            "[00:00:18] The speaker expects lower inflation to reduce expected policy rates.",
            "[00:00:32] Lower expected rates can support long-duration Treasury prices.",
            "[00:00:48] The speaker is monitoring TLT but is not entering a trade today.",
            "[00:01:03] A renewed inflation acceleration would invalidate the thesis.",
        ]
    )
    summary = client.summarize(video, transcript)
    assert summary["creator_thesis"]
    assert isinstance(summary["why_chains"], list)
    assert isinstance(summary["assets"], list)
    print(
        "Ollama smoke test passed: "
        f"relevant={classification['is_relevant']} "
        f"summary_confidence={summary['confidence']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
