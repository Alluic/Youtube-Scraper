from datetime import UTC, datetime
from pathlib import Path

from youtube_digest.storage import Storage


def video() -> dict:
    return {
        "video_id": "abc123",
        "channel_id": "channel",
        "channel_title": "Macro Channel",
        "title": "Inflation update",
        "description": "Rates and markets",
        "published_at": "2026-07-30T10:00:00+00:00",
        "duration_seconds": 600,
        "url": "https://www.youtube.com/watch?v=abc123",
    }


def test_video_upsert_is_idempotent(tmp_path: Path) -> None:
    with Storage(tmp_path / "state.db") as storage:
        run_id = storage.start_run(datetime.now(UTC))

        assert storage.upsert_video(video(), run_id) is True
        assert storage.upsert_video(video(), run_id) is False
        storage.commit()

        rows = storage.list_processing_candidates(3)
        assert len(rows) == 1
        assert rows[0]["video_id"] == "abc123"


def test_outbox_completes_batch_and_video(tmp_path: Path) -> None:
    with Storage(tmp_path / "state.db") as storage:
        run_id = storage.start_run(datetime.now(UTC))
        storage.upsert_video(video(), run_id)
        storage.commit()
        storage.update_video("abc123", status="summarized", summary_json="{}")

        storage.queue_batch(run_id, ["abc123"], ["one", "two"])
        pending = storage.pending_outbox()
        assert len(pending) == 2
        assert storage.complete_delivered_batches() == 0

        for item in pending:
            storage.mark_outbox_sent(item["outbox_id"], str(item["outbox_id"]))

        assert storage.complete_delivered_batches() == 1
        row = storage.rows_for_ids(["abc123"])[0]
        assert row["status"] == "delivered"
        assert not storage.pending_outbox()
