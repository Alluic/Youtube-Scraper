import pytest

from youtube_digest.ollama_client import (
    CLASSIFICATION_SCHEMA,
    OllamaClient,
    chunk_transcript,
    classification_decision,
)


def test_classification_thresholds() -> None:
    assert (
        classification_decision(
            {"is_relevant": True, "confidence": 0.70}, 0.70, 0.85
        )
        == "include"
    )
    assert (
        classification_decision(
            {"is_relevant": False, "confidence": 0.85}, 0.70, 0.85
        )
        == "exclude"
    )
    assert (
        classification_decision(
            {"is_relevant": False, "confidence": 0.50}, 0.70, 0.85
        )
        == "ambiguous"
    )


def test_transcript_chunking_preserves_timestamp_lines() -> None:
    transcript = "\n".join(f"[00:00:{index:02d}] statement {index}" for index in range(40))

    chunks = chunk_transcript(transcript, max_chars=200, overlap_chars=40)

    assert len(chunks) > 1
    assert chunks[0].startswith("[00:00:00]")
    assert chunks[-1].endswith("statement 39")
    assert all(chunk.strip() for chunk in chunks)


def test_schema_validation_rejects_wrong_types() -> None:
    invalid = {
        "is_relevant": "yes",
        "confidence": 0.8,
        "category": "finance",
        "reason": "test",
        "core_topics": [],
    }

    with pytest.raises(ValueError, match="boolean"):
        OllamaClient._validate_required(invalid, CLASSIFICATION_SCHEMA)
