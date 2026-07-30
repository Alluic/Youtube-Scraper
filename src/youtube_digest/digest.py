from __future__ import annotations

import html
import json
import re
import sqlite3
import textwrap
from collections.abc import Sequence
from typing import Any


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _escaped_parts(value: Any, width: int = 700) -> list[str]:
    text = _clean(value)
    if not text:
        return []
    return [html.escape(part) for part in textwrap.wrap(text, width=width) or [text]]


def _labeled_lines(label: str, values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    lines: list[str] = []
    first = True
    for value in values:
        for part in _escaped_parts(value):
            prefix = f"<b>{html.escape(label)}:</b> " if first else "• "
            lines.append(prefix + part)
            first = False
    return lines


def _timestamp_url(video_url: str, seconds: int) -> str:
    separator = "&" if "?" in video_url else "?"
    return f"{video_url}{separator}t={max(0, int(seconds))}s"


def pack_html_lines(lines: Sequence[str], max_chars: int = 3_500) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in lines:
        if len(line) > max_chars:
            plain = re.sub(r"<[^>]+>", "", line)
            subdivisions = _escaped_parts(html.unescape(plain), width=max_chars // 2)
        else:
            subdivisions = [line]
        for part in subdivisions:
            addition = len(part) + (1 if current else 0)
            if current and current_size + addition > max_chars:
                chunks.append("\n".join(current))
                current = []
                current_size = 0
            current.append(part)
            current_size += len(part) + (1 if current_size else 0)
    if current:
        chunks.append("\n".join(current))
    count = len(chunks)
    return [
        f"<b>YouTube Investor Digest — Part {index}/{count}</b>\n{chunk}"
        for index, chunk in enumerate(chunks, start=1)
    ]


def render_digest_messages(
    synthesis: dict[str, Any],
    videos: Sequence[sqlite3.Row | dict[str, Any]],
) -> list[str]:
    lines: list[str] = ["<b>Cross-video synthesis</b>"]
    lines.extend(_labeled_lines("Dominant themes", synthesis.get("dominant_themes")))
    lines.extend(_labeled_lines("Agreements", synthesis.get("agreements")))
    lines.extend(_labeled_lines("Disagreements", synthesis.get("disagreements")))
    lines.extend(_labeled_lines("Repeated assets", synthesis.get("repeated_assets")))
    lines.extend(_labeled_lines("Watch items", synthesis.get("watch_items")))

    for row in videos:
        data = dict(row)
        summary = json.loads(data["summary_json"])
        title = html.escape(_clean(data["title"]))
        channel = html.escape(_clean(data["channel_title"]))
        video_url = html.escape(data["url"], quote=True)
        source = html.escape(_clean(data.get("transcript_source") or "unknown"))
        published = html.escape(_clean(data.get("published_at") or "unknown publication time"))
        duration = data.get("duration_seconds")
        duration_text = f"{int(duration) // 60}m" if duration else "unknown duration"
        lines.extend(
            [
                "",
                f"<b><a href=\"{video_url}\">{title}</a></b>",
                f"{channel} · {published} · {html.escape(duration_text)} · transcript: {source}",
            ]
        )
        lines.extend(_labeled_lines("Creator thesis", summary.get("creator_thesis")))
        lines.extend(_labeled_lines("Creator actions", summary.get("creator_actions")))

        assets = []
        for asset in summary.get("assets", []):
            ticker = _clean(asset.get("ticker"))
            name = _clean(asset.get("name"))
            asset_class = _clean(asset.get("asset_class"))
            direction = _clean(asset.get("direction"))
            identity = f"{ticker} ({name})" if ticker and name else ticker or name
            assets.append(
                " / ".join(part for part in (identity, asset_class, direction) if part)
            )
        lines.extend(_labeled_lines("Core assets", assets))

        why_lines = []
        for chain in summary.get("why_chains", []):
            why_lines.append(
                f"{_clean(chain.get('driver'))} → {_clean(chain.get('mechanism'))} → "
                f"{_clean(chain.get('affected_asset'))} → {_clean(chain.get('action'))}"
            )
        lines.extend(_labeled_lines("WHY", why_lines))

        evidence_lines = []
        for evidence in summary.get("evidence", []):
            seconds = int(evidence.get("timestamp_seconds", 0))
            timestamp = f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
            link = html.escape(_timestamp_url(data["url"], seconds), quote=True)
            claim = html.escape(_clean(evidence.get("claim")))
            evidence_lines.append(f"<a href=\"{link}\">{timestamp}</a> — {claim}")
        if evidence_lines:
            lines.append("<b>Evidence:</b>")
            lines.extend(f"• {line}" for line in evidence_lines)

        lines.extend(_labeled_lines("Catalysts", summary.get("catalysts")))
        lines.extend(_labeled_lines("Time horizon", summary.get("time_horizon")))
        lines.extend(_labeled_lines("Investor implications", summary.get("investor_implications")))
        lines.extend(_labeled_lines("Risks", summary.get("risks")))
        lines.extend(_labeled_lines("Counterarguments", summary.get("counterarguments")))
        lines.extend(
            _labeled_lines("Invalidation", summary.get("invalidation_conditions"))
        )
        lines.extend(_labeled_lines("Confidence", summary.get("confidence")))

    lines.extend(
        [
            "",
            "<i>Research digest only. Creator claims and model-derived implications are "
            "separated; neither is personalized financial advice.</i>",
        ]
    )
    return pack_html_lines(lines)
