from __future__ import annotations

import html
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from youtube_digest.config import AppConfig, get_telegram_token
from youtube_digest.digest import render_digest_messages
from youtube_digest.lock import ProcessLock
from youtube_digest.ollama_client import OllamaClient, classification_decision
from youtube_digest.storage import Storage, utc_now
from youtube_digest.telegram import TelegramClient
from youtube_digest.transcripts import TranscriptProvider, WhisperTranscriber
from youtube_digest.youtube import YouTubeDiscovery, build_youtube_service


@dataclass(slots=True)
class RunResult:
    run_id: str
    discovered: int = 0
    delivered: int = 0
    failures: list[str] = field(default_factory=list)
    preview_messages: list[str] = field(default_factory=list)


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def _override_decision(video: dict[str, Any], config: AppConfig) -> str | None:
    channel = str(video["channel_title"]).casefold()
    text = f"{video['title']} {video.get('description', '')}".casefold()
    if any(value.casefold() == channel for value in config.exclude_channels):
        return "exclude"
    if any(value.casefold() in text for value in config.exclude_keywords):
        return "exclude"
    if any(value.casefold() == channel for value in config.include_channels):
        return "include"
    if any(value.casefold() in text for value in config.include_keywords):
        return "include"
    return None


def _override_classification(decision: str) -> dict[str, Any]:
    relevant = decision == "include"
    return {
        "is_relevant": relevant,
        "confidence": 1.0,
        "category": "mixed" if relevant else "not_relevant",
        "reason": f"Configuration {decision} override.",
        "core_topics": [],
        "decision": decision,
        "classification_stage": "override",
    }


def _determine_since(storage: Storage, explicit: datetime | None) -> datetime:
    if explicit:
        return explicit.astimezone(UTC)
    watermark = storage.get_meta("discovery_watermark")
    if watermark:
        parsed = datetime.fromisoformat(watermark.replace("Z", "+00:00")).astimezone(UTC)
        return parsed - timedelta(hours=2)
    return utc_now() - timedelta(hours=24)


def _read_transcript(path: str | None) -> str:
    if not path:
        raise FileNotFoundError("Video has no transcript path.")
    transcript_path = Path(path)
    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")
    return transcript_path.read_text(encoding="utf-8")


def _flush_outbox(storage: Storage, telegram: TelegramClient) -> int:
    for message in storage.pending_outbox():
        message_id = telegram.send_message(message["payload_html"])
        storage.mark_outbox_sent(message["outbox_id"], message_id)
    return storage.complete_delivered_batches()


def _send_failure_alert(telegram: TelegramClient, failures: list[str]) -> None:
    if not failures:
        return
    selected = failures[:10]
    body = "<b>YouTube Investor Digest failures</b>\n" + "\n".join(
        f"• {html.escape(failure[:300])}" for failure in selected
    )
    if len(failures) > len(selected):
        body += f"\n• {len(failures) - len(selected)} additional failures are in local logs."
    telegram.send_message(body[:3900])


def run_pipeline(
    config: AppConfig,
    logger: logging.Logger,
    since: datetime | None = None,
    no_send: bool = False,
) -> RunResult:
    config.ensure_directories()
    with ProcessLock(config.data_dir / "run.lock"), Storage(config.database_path) as storage:
        since_at = _determine_since(storage, since)
        run_id = storage.start_run(since_at)
        result = RunResult(run_id=run_id)
        telegram: TelegramClient | None = None
        try:
            if not no_send:
                telegram = TelegramClient(get_telegram_token(), config.telegram_chat_id)
                result.delivered += _flush_outbox(storage, telegram)

            ollama = OllamaClient(config.ollama_url, config.ollama_model, logger)
            ollama.ensure_running()

            service = build_youtube_service(config.oauth_token_path)
            discovery = YouTubeDiscovery(service, storage, logger)
            scan_started = utc_now()
            discovered_ids = discovery.discover(since_at, run_id)
            result.discovered = len(discovered_ids)
            storage.set_meta("discovery_watermark", scan_started.isoformat())

            candidates = storage.list_processing_candidates(config.max_attempts)
            for row in candidates:
                video = _row_dict(row)
                if video["status"] in {"classified", "transcript_ready"}:
                    continue
                try:
                    override = _override_decision(video, config)
                    if override:
                        classification = _override_classification(override)
                    else:
                        classification = ollama.classify(video)
                        classification["decision"] = classification_decision(
                            classification,
                            config.include_confidence,
                            config.exclude_confidence,
                        )
                        classification["classification_stage"] = "metadata"
                    if classification["decision"] == "exclude":
                        storage.set_json(
                            video["video_id"],
                            "classification_json",
                            classification,
                            status="filtered_out",
                            last_error=None,
                        )
                    else:
                        storage.set_json(
                            video["video_id"],
                            "classification_json",
                            classification,
                            status="classified",
                            last_error=None,
                        )
                except Exception as exc:
                    message = f"{video['video_id']} classification: {exc}"
                    logger.exception(message)
                    storage.record_failure(video["video_id"], message)
                    result.failures.append(message)

            transcript_provider = TranscriptProvider(
                config.transcript_dir,
                config.temp_dir,
                config.language,
                logger,
            )
            whisper_needed: list[dict[str, Any]] = []
            for row in storage.list_by_status(["classified"]):
                video = _row_dict(row)
                existing_path = video.get("transcript_path")
                if existing_path and Path(existing_path).exists():
                    storage.update_video(video["video_id"], status="transcript_ready")
                    continue
                try:
                    caption = transcript_provider.captions(video["video_id"], video["url"])
                    if caption:
                        transcript_path, source = caption
                        storage.update_video(
                            video["video_id"],
                            status="transcript_ready",
                            transcript_path=str(transcript_path),
                            transcript_source=source,
                            last_error=None,
                        )
                    else:
                        whisper_needed.append(video)
                except Exception as exc:
                    logger.warning(
                        "Caption retrieval failed for %s; trying Whisper: %s",
                        video["video_id"],
                        exc,
                    )
                    whisper_needed.append(video)

            if whisper_needed:
                ollama.unload()
                transcriber = WhisperTranscriber(config.whisper_model, logger)
                for video in whisper_needed:
                    work: Path | None = None
                    try:
                        audio, work = transcript_provider.download_audio(
                            video["video_id"], video["url"]
                        )
                        transcript = transcriber.transcribe(audio)
                        transcript_path = transcript_provider.save_whisper(
                            video["video_id"], transcript
                        )
                        storage.update_video(
                            video["video_id"],
                            status="transcript_ready",
                            transcript_path=str(transcript_path),
                            transcript_source="whisper_medium_en",
                            last_error=None,
                        )
                    except Exception as exc:
                        message = f"{video['video_id']} transcription: {exc}"
                        logger.exception(message)
                        storage.record_failure(video["video_id"], message)
                        result.failures.append(message)
                    finally:
                        if work:
                            shutil.rmtree(work, ignore_errors=True)

            for row in storage.list_by_status(["transcript_ready"]):
                video = _row_dict(row)
                try:
                    classification = json.loads(video["classification_json"])
                    transcript = _read_transcript(video["transcript_path"])
                    if classification.get("decision") == "ambiguous":
                        second = ollama.classify(video, transcript_excerpt=transcript)
                        second_decision = classification_decision(
                            second,
                            max(0.60, config.include_confidence - 0.10),
                            max(0.75, config.exclude_confidence - 0.10),
                        )
                        # After transcript-level review, preserve uncertain finance content
                        # rather than creating a false negative.
                        second["decision"] = (
                            "exclude" if second_decision == "exclude" else "include"
                        )
                        second["classification_stage"] = "transcript"
                        classification = second
                        storage.set_json(
                            video["video_id"],
                            "classification_json",
                            classification,
                        )
                    if classification.get("decision") == "exclude":
                        storage.update_video(video["video_id"], status="filtered_out")
                        continue
                    summary = ollama.summarize(video, transcript)
                    storage.set_json(
                        video["video_id"],
                        "summary_json",
                        summary,
                        status="summarized",
                        last_error=None,
                    )
                except Exception as exc:
                    message = f"{video['video_id']} summarization: {exc}"
                    logger.exception(message)
                    storage.record_failure(video["video_id"], message)
                    result.failures.append(message)

            ready = storage.summarized_unqueued()
            if ready:
                summary_values = [json.loads(row["summary_json"]) for row in ready]
                synthesis = ollama.synthesize(summary_values)
                messages = render_digest_messages(synthesis, ready)
                if no_send:
                    result.preview_messages = messages
                else:
                    storage.queue_batch(
                        run_id,
                        [row["video_id"] for row in ready],
                        messages,
                    )
                    if telegram is None:  # pragma: no cover - defensive
                        raise RuntimeError("Telegram client is unavailable.")
                    result.delivered += _flush_outbox(storage, telegram)

            removed = storage.cleanup_transcripts(
                config.transcript_dir, config.transcript_retention_days
            )
            if removed:
                logger.info("Removed %s expired transcript files", removed)

            if telegram and result.failures:
                try:
                    _send_failure_alert(telegram, result.failures)
                except Exception:
                    logger.exception("Unable to send failure alert")

            status = "partial" if result.failures else "success"
            storage.finish_run(
                run_id,
                status,
                discovered_count=result.discovered,
                delivered_count=result.delivered,
                failure_count=len(result.failures),
            )
            return result
        except Exception as exc:
            logger.exception("Run %s failed", run_id)
            storage.finish_run(
                run_id,
                "failed",
                discovered_count=result.discovered,
                delivered_count=result.delivered,
                failure_count=len(result.failures) + 1,
                error=str(exc),
            )
            if telegram:
                try:
                    _send_failure_alert(telegram, [f"Run failed: {exc}"])
                except Exception:
                    logger.exception("Unable to send terminal failure alert")
            raise
