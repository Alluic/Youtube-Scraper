from pathlib import Path
from types import SimpleNamespace

from youtube_digest.transcripts import (
    WhisperTranscriber,
    format_timestamp,
    normalize_vtt,
)


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


def test_cuda_runtime_error_detection() -> None:
    assert WhisperTranscriber._is_cuda_runtime_error(
        RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
    )
    assert not WhisperTranscriber._is_cuda_runtime_error(
        RuntimeError("Whisper returned an empty transcript.")
    )


def test_transcription_retries_on_cpu_after_lazy_cuda_failure() -> None:
    class Logger:
        def warning(self, *_args: object) -> None:
            pass

    class CudaModel:
        def transcribe(self, *_args: object, **_kwargs: object) -> tuple[object, None]:
            def segments() -> object:
                raise RuntimeError("Library cublas64_12.dll is not found")
                yield  # pragma: no cover

            return segments(), None

    class CpuModel:
        def transcribe(self, *_args: object, **_kwargs: object) -> tuple[list[object], None]:
            return [SimpleNamespace(start=1.0, text="CPU fallback worked.")], None

    class TestTranscriber(WhisperTranscriber):
        def _load(self) -> object:
            return CudaModel() if self._device == "cuda" else CpuModel()

    transcriber = TestTranscriber("medium.en", Logger())

    transcript = transcriber.transcribe(Path("unused-audio.webm"))

    assert transcriber._device == "cpu"
    assert transcript == "[00:00:01] CPU fallback worked."
