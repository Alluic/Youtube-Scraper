from __future__ import annotations

import html
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_TIMING_LINE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[.,]\d{3})"
)
_TAG = re.compile(r"<[^>]+>")


def timestamp_to_seconds(value: str) -> int:
    normalized = value.replace(",", ".")
    hours, minutes, seconds = normalized.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + int(float(seconds))


def format_timestamp(seconds: int | float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def normalize_vtt(text: str) -> str:
    lines = text.replace("\ufeff", "").splitlines()
    segments: list[str] = []
    current_start: int | None = None
    current_text: list[str] = []

    def flush() -> None:
        nonlocal current_text
        if current_start is None or not current_text:
            current_text = []
            return
        cleaned = " ".join(current_text)
        cleaned = html.unescape(_TAG.sub("", cleaned))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            rendered = f"[{format_timestamp(current_start)}] {cleaned}"
            if not segments or segments[-1] != rendered:
                segments.append(rendered)
        current_text = []

    for raw_line in lines:
        line = raw_line.strip()
        timing = _TIMING_LINE.search(line)
        if timing:
            flush()
            current_start = timestamp_to_seconds(timing.group("start"))
            continue
        if not line or line == "WEBVTT" or line.startswith(("NOTE", "Kind:", "Language:")):
            continue
        if line.isdigit():
            continue
        if current_start is not None:
            current_text.append(line)
    flush()

    deduplicated: list[str] = []
    prior_text = ""
    for segment in segments:
        _, _, segment_text = segment.partition("] ")
        if segment_text == prior_text:
            continue
        deduplicated.append(segment)
        prior_text = segment_text
    return "\n".join(deduplicated)


def normalized_whisper_segments(segments: Iterable[Any]) -> str:
    lines: list[str] = []
    for segment in segments:
        text = re.sub(r"\s+", " ", str(segment.text)).strip()
        if text:
            lines.append(f"[{format_timestamp(segment.start)}] {text}")
    return "\n".join(lines)


class TranscriptProvider:
    def __init__(self, transcript_dir: Path, temp_dir: Path, language: str, logger: Any):
        self.transcript_dir = transcript_dir
        self.temp_dir = temp_dir
        self.language = language
        self.logger = logger
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def _download_subtitle_kind(
        self, video_id: str, url: str, automatic: bool
    ) -> Path | None:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:  # pragma: no cover - installation guard
            raise RuntimeError("The `yt-dlp` package is not installed.") from exc

        work = self.temp_dir / f"{video_id}-subtitles"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "writesubtitles": not automatic,
            "writeautomaticsub": automatic,
            "subtitleslangs": [self.language, f"{self.language}.*"],
            "subtitlesformat": "vtt/best",
            "outtmpl": str(work / f"{video_id}.%(ext)s"),
        }
        try:
            with YoutubeDL(options) as ydl:
                ydl.download([url])
            candidates = sorted(work.glob("*.vtt"))
            return candidates[0] if candidates else None
        except Exception:
            self.logger.debug(
                "Subtitle retrieval failed for %s (%s)",
                video_id,
                "automatic" if automatic else "manual",
                exc_info=True,
            )
            return None

    def captions(self, video_id: str, url: str) -> tuple[Path, str] | None:
        for automatic, source in ((False, "manual_captions"), (True, "auto_captions")):
            subtitle_path = self._download_subtitle_kind(video_id, url, automatic)
            if not subtitle_path:
                continue
            normalized = normalize_vtt(subtitle_path.read_text(encoding="utf-8"))
            if not normalized.strip():
                continue
            target = self.transcript_dir / f"{video_id}.txt"
            target.write_text(normalized, encoding="utf-8")
            shutil.rmtree(subtitle_path.parent, ignore_errors=True)
            return target, source
        return None

    def download_audio(self, video_id: str, url: str) -> tuple[Path, Path]:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("The `yt-dlp` package is not installed.") from exc
        work = self.temp_dir / f"{video_id}-audio"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "outtmpl": str(work / f"{video_id}.%(ext)s"),
        }
        with YoutubeDL(options) as ydl:
            ydl.download([url])
        candidates = [
            path
            for path in work.iterdir()
            if path.is_file() and path.suffix.lower() not in {".part", ".ytdl"}
        ]
        if not candidates:
            raise RuntimeError(f"yt-dlp produced no audio file for {video_id}")
        return candidates[0], work

    def save_whisper(self, video_id: str, transcript: str) -> Path:
        target = self.transcript_dir / f"{video_id}.txt"
        target.write_text(transcript, encoding="utf-8")
        return target


class WhisperTranscriber:
    def __init__(self, model_name: str, logger: Any) -> None:
        self.model_name = model_name
        self.logger = logger
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("The `faster-whisper` package is not installed.") from exc
            self.logger.info("Loading Whisper model %s on CUDA", self.model_name)
            try:
                self._model = WhisperModel(
                    self.model_name,
                    device="cuda",
                    compute_type="float16",
                )
            except Exception:
                self.logger.warning(
                    "CUDA Whisper initialization failed; using CPU int8",
                    exc_info=True,
                )
                self._model = WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type="int8",
                )
        return self._model

    def transcribe(self, audio_path: Path) -> str:
        model = self._load()
        segments, _info = model.transcribe(
            str(audio_path),
            beam_size=5,
            vad_filter=True,
        )
        transcript = normalized_whisper_segments(segments)
        if not transcript.strip():
            raise RuntimeError("Whisper returned an empty transcript.")
        return transcript
