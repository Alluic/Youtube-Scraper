from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


class Storage:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.initialize()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                uploads_playlist_id TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                since_at TEXT,
                discovered_count INTEGER NOT NULL DEFAULT 0,
                delivered_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                channel_title TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL,
                duration_seconds INTEGER,
                url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'discovered',
                classification_json TEXT,
                transcript_source TEXT,
                transcript_path TEXT,
                summary_json TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                discovered_run_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                delivered_at TEXT,
                FOREIGN KEY(discovered_run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS digest_batches (
                batch_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                video_ids_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                delivered_at TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS outbox (
                outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                payload_html TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                telegram_message_id TEXT,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                UNIQUE(batch_id, sequence),
                FOREIGN KEY(batch_id) REFERENCES digest_batches(batch_id)
            );

            CREATE INDEX IF NOT EXISTS idx_videos_status
                ON videos(status, attempts, published_at);
            CREATE INDEX IF NOT EXISTS idx_outbox_status
                ON outbox(status, outbox_id);
            """
        )
        self.connection.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.connection.execute(
            """
            INSERT INTO meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.connection.commit()

    def start_run(self, since_at: datetime) -> str:
        run_id = str(uuid.uuid4())
        self.connection.execute(
            "INSERT INTO runs(run_id, started_at, status, since_at) VALUES (?, ?, 'running', ?)",
            (run_id, iso_now(), since_at.isoformat()),
        )
        self.connection.commit()
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        discovered_count: int = 0,
        delivered_count: int = 0,
        failure_count: int = 0,
        error: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE runs
            SET finished_at = ?, status = ?, discovered_count = ?,
                delivered_count = ?, failure_count = ?, error = ?
            WHERE run_id = ?
            """,
            (
                iso_now(),
                status,
                discovered_count,
                delivered_count,
                failure_count,
                error,
                run_id,
            ),
        )
        self.connection.commit()

    def upsert_channel(self, channel_id: str, title: str, uploads_playlist_id: str) -> None:
        self.connection.execute(
            """
            INSERT INTO channels(channel_id, title, uploads_playlist_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                title = excluded.title,
                uploads_playlist_id = excluded.uploads_playlist_id,
                updated_at = excluded.updated_at
            """,
            (channel_id, title, uploads_playlist_id, iso_now()),
        )

    def get_channel(self, channel_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
        ).fetchone()

    def upsert_video(self, video: dict[str, Any], run_id: str) -> bool:
        exists = self.connection.execute(
            "SELECT 1 FROM videos WHERE video_id = ?", (video["video_id"],)
        ).fetchone()
        now = iso_now()
        self.connection.execute(
            """
            INSERT INTO videos(
                video_id, channel_id, channel_title, title, description,
                published_at, duration_seconds, url, discovered_run_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                channel_title = excluded.channel_title,
                title = excluded.title,
                description = excluded.description,
                published_at = excluded.published_at,
                duration_seconds = COALESCE(excluded.duration_seconds, videos.duration_seconds),
                url = excluded.url,
                updated_at = excluded.updated_at
            """,
            (
                video["video_id"],
                video["channel_id"],
                video["channel_title"],
                video["title"],
                video.get("description", ""),
                video["published_at"],
                video.get("duration_seconds"),
                video["url"],
                run_id,
                now,
                now,
            ),
        )
        return not bool(exists)

    def commit(self) -> None:
        self.connection.commit()

    def list_processing_candidates(self, max_attempts: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT * FROM videos
                WHERE status IN ('discovered', 'failed', 'classified', 'transcript_ready')
                  AND attempts < ?
                ORDER BY published_at ASC
                """,
                (max_attempts,),
            )
        )

    def list_by_status(self, statuses: Sequence[str]) -> list[sqlite3.Row]:
        if not statuses:
            return []
        marks = ",".join("?" for _ in statuses)
        return list(
            self.connection.execute(
                f"SELECT * FROM videos WHERE status IN ({marks}) ORDER BY published_at ASC",
                tuple(statuses),
            )
        )

    def update_video(self, video_id: str, **fields: Any) -> None:
        allowed = {
            "status",
            "classification_json",
            "transcript_source",
            "transcript_path",
            "summary_json",
            "last_error",
            "attempts",
            "delivered_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unsupported video fields: {sorted(unknown)}")
        fields["updated_at"] = iso_now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [fields[key] for key in fields]
        self.connection.execute(
            f"UPDATE videos SET {assignments} WHERE video_id = ?",
            (*values, video_id),
        )
        self.connection.commit()

    def set_json(self, video_id: str, field: str, value: dict[str, Any], **extra: Any) -> None:
        if field not in {"classification_json", "summary_json"}:
            raise ValueError(field)
        self.update_video(video_id, **{field: json.dumps(value, ensure_ascii=False), **extra})

    def record_failure(self, video_id: str, error: str) -> None:
        row = self.connection.execute(
            "SELECT attempts FROM videos WHERE video_id = ?", (video_id,)
        ).fetchone()
        attempts = int(row["attempts"]) + 1 if row else 1
        self.update_video(
            video_id,
            status="failed",
            attempts=attempts,
            last_error=error[:2000],
        )

    def summarized_unqueued(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM videos WHERE status = 'summarized' ORDER BY published_at ASC"
            )
        )

    def queue_batch(self, run_id: str, video_ids: Sequence[str], messages: Sequence[str]) -> str:
        batch_id = str(uuid.uuid4())
        now = iso_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO digest_batches(batch_id, run_id, video_ids_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (batch_id, run_id, json.dumps(list(video_ids)), now),
            )
            self.connection.executemany(
                """
                INSERT INTO outbox(batch_id, sequence, payload_html, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [(batch_id, sequence, payload, now) for sequence, payload in enumerate(messages)],
            )
            marks = ",".join("?" for _ in video_ids)
            if video_ids:
                self.connection.execute(
                    f"UPDATE videos SET status = 'queued', updated_at = ? "
                    f"WHERE video_id IN ({marks})",
                    (now, *video_ids),
                )
        return batch_id

    def pending_outbox(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM outbox WHERE status = 'pending' ORDER BY outbox_id ASC"
            )
        )

    def mark_outbox_sent(self, outbox_id: int, telegram_message_id: str) -> None:
        self.connection.execute(
            """
            UPDATE outbox
            SET status = 'sent', telegram_message_id = ?, sent_at = ?
            WHERE outbox_id = ?
            """,
            (telegram_message_id, iso_now(), outbox_id),
        )
        self.connection.commit()

    def complete_delivered_batches(self) -> int:
        rows = list(
            self.connection.execute(
                """
                SELECT b.batch_id, b.video_ids_json
                FROM digest_batches b
                WHERE b.status = 'queued'
                  AND NOT EXISTS (
                    SELECT 1 FROM outbox o
                    WHERE o.batch_id = b.batch_id AND o.status != 'sent'
                  )
                """
            )
        )
        delivered = 0
        now = iso_now()
        with self.connection:
            for row in rows:
                video_ids = json.loads(row["video_ids_json"])
                self.connection.execute(
                    "UPDATE digest_batches SET status = 'delivered', delivered_at = ? "
                    "WHERE batch_id = ?",
                    (now, row["batch_id"]),
                )
                if video_ids:
                    marks = ",".join("?" for _ in video_ids)
                    self.connection.execute(
                        f"UPDATE videos SET status = 'delivered', delivered_at = ?, updated_at = ? "
                        f"WHERE video_id IN ({marks})",
                        (now, now, *video_ids),
                    )
                    delivered += len(video_ids)
        return delivered

    def cleanup_transcripts(self, transcript_dir: Path, retention_days: int) -> int:
        cutoff = utc_now() - timedelta(days=retention_days)
        removed = 0
        for path in transcript_dir.glob("*.txt"):
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified < cutoff:
                path.unlink(missing_ok=True)
                self.connection.execute(
                    """
                    UPDATE videos
                    SET transcript_path = NULL, updated_at = ?
                    WHERE transcript_path = ?
                    """,
                    (iso_now(), str(path)),
                )
                removed += 1
        self.connection.commit()
        return removed

    def permanently_failed(self, max_attempts: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM videos WHERE status = 'failed' AND attempts >= ?",
                (max_attempts,),
            )
        )

    def rows_for_ids(self, video_ids: Iterable[str]) -> list[sqlite3.Row]:
        values = list(video_ids)
        if not values:
            return []
        marks = ",".join("?" for _ in values)
        return list(
            self.connection.execute(
                f"SELECT * FROM videos WHERE video_id IN ({marks}) ORDER BY published_at ASC",
                values,
            )
        )
