from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any

CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_relevant": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "category": {
            "type": "string",
            "enum": ["finance", "macro", "trading", "mixed", "not_relevant"],
        },
        "reason": {"type": "string"},
        "core_topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["is_relevant", "confidence", "category", "reason", "core_topics"],
}

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "creator_thesis": {"type": "string"},
        "creator_actions": {"type": "array", "items": {"type": "string"}},
        "investor_implications": {"type": "array", "items": {"type": "string"}},
        "assets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "ticker": {"type": "string"},
                    "asset_class": {"type": "string"},
                    "direction": {"type": "string"},
                },
                "required": ["name", "ticker", "asset_class", "direction"],
            },
        },
        "why_chains": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "driver": {"type": "string"},
                    "mechanism": {"type": "string"},
                    "affected_asset": {"type": "string"},
                    "action": {"type": "string"},
                },
                "required": ["driver", "mechanism", "affected_asset", "action"],
            },
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "timestamp_seconds": {"type": "integer", "minimum": 0},
                },
                "required": ["claim", "timestamp_seconds"],
            },
        },
        "catalysts": {"type": "array", "items": {"type": "string"}},
        "time_horizon": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "counterarguments": {"type": "array", "items": {"type": "string"}},
        "invalidation_conditions": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "creator_thesis",
        "creator_actions",
        "investor_implications",
        "assets",
        "why_chains",
        "evidence",
        "catalysts",
        "time_horizon",
        "risks",
        "counterarguments",
        "invalidation_conditions",
        "confidence",
    ],
}

PARTIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "string"}},
        "actions": {"type": "array", "items": {"type": "string"}},
        "assets": {"type": "array", "items": {"type": "string"}},
        "why_chains": {"type": "array", "items": {"type": "string"}},
        "evidence_with_timestamps": {"type": "array", "items": {"type": "string"}},
        "catalysts": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "claims",
        "actions",
        "assets",
        "why_chains",
        "evidence_with_timestamps",
        "catalysts",
        "risks",
    ],
}

SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "dominant_themes": {"type": "array", "items": {"type": "string"}},
        "agreements": {"type": "array", "items": {"type": "string"}},
        "disagreements": {"type": "array", "items": {"type": "string"}},
        "repeated_assets": {"type": "array", "items": {"type": "string"}},
        "watch_items": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "dominant_themes",
        "agreements",
        "disagreements",
        "repeated_assets",
        "watch_items",
    ],
}


def chunk_transcript(
    transcript: str,
    max_chars: int = 44_000,
    overlap_chars: int = 2_000,
) -> list[str]:
    if len(transcript) <= max_chars:
        return [transcript]
    lines = transcript.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        addition = len(line) + 1
        if current and size + addition > max_chars:
            chunks.append("\n".join(current))
            overlap: list[str] = []
            overlap_size = 0
            for previous in reversed(current):
                if overlap_size + len(previous) + 1 > overlap_chars:
                    break
                overlap.insert(0, previous)
                overlap_size += len(previous) + 1
            current = overlap
            size = overlap_size
        current.append(line)
        size += addition
    if current:
        chunks.append("\n".join(current))
    return chunks


def classification_decision(
    classification: dict[str, Any],
    include_confidence: float,
    exclude_confidence: float,
) -> str:
    confidence = float(classification["confidence"])
    if classification["is_relevant"] and confidence >= include_confidence:
        return "include"
    if not classification["is_relevant"] and confidence >= exclude_confidence:
        return "exclude"
    return "ambiguous"


class OllamaClient:
    def __init__(self, base_url: str, model: str, logger: Any) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.logger = logger

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 600,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def healthy(self) -> bool:
        try:
            response = self._request("GET", "/api/tags", timeout=5)
            return isinstance(response.get("models"), list)
        except Exception:
            return False

    def ensure_running(self, wait_seconds: int = 60) -> None:
        if self.healthy():
            return
        executable = shutil.which("ollama")
        if not executable:
            raise RuntimeError("Ollama is not installed or not available on PATH.")
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        subprocess.Popen(
            [executable, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.healthy():
                return
            time.sleep(1)
        raise RuntimeError(f"Ollama did not become ready within {wait_seconds} seconds.")

    def unload(self) -> None:
        try:
            self._request(
                "POST",
                "/api/generate",
                {"model": self.model, "prompt": "", "keep_alive": 0, "stream": False},
                timeout=30,
            )
        except Exception:
            self.logger.warning("Unable to unload Ollama model", exc_info=True)

    def _chat_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        prompt = user
        if schema is CLASSIFICATION_SCHEMA:
            max_output_tokens = 600
        elif schema is SUMMARY_SCHEMA:
            max_output_tokens = 3_000
        else:
            max_output_tokens = 1_800
        for attempt in range(2):
            try:
                response = self._request(
                    "POST",
                    "/api/chat",
                    {
                        "model": self.model,
                        "stream": False,
                        "think": False,
                        "format": schema,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "options": {
                            "temperature": 0.1,
                            "num_ctx": 16_384,
                            "num_predict": max_output_tokens,
                        },
                        "keep_alive": "10m",
                    },
                )
                content = response.get("message", {}).get("content", "")
                parsed = json.loads(content)
                self._validate_required(parsed, schema)
                return parsed
            except Exception as exc:
                last_error = exc
                prompt = (
                    "Return only valid JSON matching the supplied schema. "
                    "Do not use markdown fences.\n\nOriginal task:\n" + user
                )
                self.logger.warning("Ollama JSON attempt %s failed: %s", attempt + 1, exc)
        raise RuntimeError(f"Ollama did not return valid structured output: {last_error}")

    @staticmethod
    def _validate_required(value: dict[str, Any], schema: dict[str, Any]) -> None:
        def validate(node: Any, rule: dict[str, Any], path: str) -> None:
            expected = rule.get("type")
            valid = True
            if expected == "object":
                valid = isinstance(node, dict)
            elif expected == "array":
                valid = isinstance(node, list)
            elif expected == "string":
                valid = isinstance(node, str)
            elif expected == "boolean":
                valid = isinstance(node, bool)
            elif expected == "number":
                valid = isinstance(node, (int, float)) and not isinstance(node, bool)
            elif expected == "integer":
                valid = isinstance(node, int) and not isinstance(node, bool)
            if not valid:
                raise ValueError(f"{path} must be {expected}, got {type(node).__name__}")
            if "enum" in rule and node not in rule["enum"]:
                raise ValueError(f"{path} is not an allowed value")
            if isinstance(node, (int, float)) and not isinstance(node, bool):
                if "minimum" in rule and node < rule["minimum"]:
                    raise ValueError(f"{path} is below minimum")
                if "maximum" in rule and node > rule["maximum"]:
                    raise ValueError(f"{path} is above maximum")
            if isinstance(node, dict):
                missing = [key for key in rule.get("required", []) if key not in node]
                if missing:
                    raise ValueError(f"{path} is missing required fields: {missing}")
                properties = rule.get("properties", {})
                for key, child_rule in properties.items():
                    if key in node:
                        validate(node[key], child_rule, f"{path}.{key}")
            if isinstance(node, list) and "items" in rule:
                for index, item in enumerate(node):
                    validate(item, rule["items"], f"{path}[{index}]")

        validate(value, schema, "$")

    def classify(
        self,
        video: dict[str, Any],
        transcript_excerpt: str | None = None,
    ) -> dict[str, Any]:
        system = (
            "You are a conservative content classifier. Determine whether a YouTube video "
            "materially concerns finance, macroeconomics, investing, markets, or trading. "
            "Do not classify general politics, entrepreneurship, or technology as relevant "
            "unless the market or investment connection is substantive."
        )
        user = (
            f"Title: {video['title']}\n"
            f"Channel: {video['channel_title']}\n"
            f"Description: {video.get('description', '')}\n"
        )
        if transcript_excerpt:
            user += f"\nTranscript excerpt:\n{transcript_excerpt[:32_000]}"
        return self._chat_json(system, user, CLASSIFICATION_SCHEMA)

    def summarize(self, video: dict[str, Any], transcript: str) -> dict[str, Any]:
        chunks = chunk_transcript(transcript)
        source: str
        if len(chunks) == 1:
            source = chunks[0]
        else:
            partials: list[dict[str, Any]] = []
            for index, chunk in enumerate(chunks, start=1):
                partials.append(
                    self._chat_json(
                        (
                            "Extract source-faithful investment claims from one transcript "
                            "chunk. Preserve timestamp strings and distinguish evidence from "
                            "opinion. Do not invent recommendations."
                        ),
                        f"Chunk {index}/{len(chunks)}:\n{chunk}",
                        PARTIAL_SCHEMA,
                    )
                )
            while len(json.dumps(partials, ensure_ascii=False)) > 44_000:
                reduced: list[dict[str, Any]] = []
                for offset in range(0, len(partials), 5):
                    reduced.append(
                        self._chat_json(
                            (
                                "Merge these source-faithful chunk extractions without dropping "
                                "material claims, assets, WHY chains, timestamps, catalysts, or "
                                "risks. Do not add facts."
                            ),
                            json.dumps(partials[offset : offset + 5], ensure_ascii=False),
                            PARTIAL_SCHEMA,
                        )
                    )
                partials = reduced
            source = "Chunk extractions:\n" + json.dumps(partials, ensure_ascii=False)

        system = (
            "You create evidence-grounded investor research briefs from video transcripts. "
            "Separate the creator's explicit claims from your inferred investor implications. "
            "Every proposed action must explain WHY through a driver, transmission mechanism, "
            "affected asset, and action. Extract only assets actually discussed. Include "
            "counterarguments, invalidation conditions, and timestamps. Never present "
            "personalized financial advice and never fabricate evidence."
        )
        user = (
            f"Video title: {video['title']}\n"
            f"Channel: {video['channel_title']}\n"
            f"Published: {video['published_at']}\n"
            f"Description: {video.get('description', '')}\n\n"
            f"Transcript evidence:\n{source}"
        )
        return self._chat_json(system, user, SUMMARY_SCHEMA)

    def synthesize(self, summaries: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if not summaries:
            return {
                "dominant_themes": [],
                "agreements": [],
                "disagreements": [],
                "repeated_assets": [],
                "watch_items": [],
            }
        serialized = json.dumps(list(summaries), ensure_ascii=False)
        if len(serialized) > 44_000:
            partial_syntheses = [
                self.synthesize(summaries[offset : offset + 5])
                for offset in range(0, len(summaries), 5)
            ]
            return self.synthesize(partial_syntheses)
        return self._chat_json(
            (
                "Synthesize several source-grounded investor video briefs. Report only themes "
                "supported by the supplied summaries. Identify agreement, disagreement, repeated "
                "assets, and concrete watch items without creating personalized advice."
            ),
            serialized,
            SYNTHESIS_SCHEMA,
        )
