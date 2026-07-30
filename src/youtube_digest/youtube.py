from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from youtube_digest.storage import Storage

YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
VIDEO_URL = "https://www.youtube.com/watch?v={video_id}"


def parse_youtube_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_iso8601_duration(value: str | None) -> int | None:
    if not value:
        return None
    match = _DURATION_PATTERN.match(value)
    if not match:
        return None
    parts = {key: int(number or 0) for key, number in match.groupdict().items()}
    return (
        parts["days"] * 86_400
        + parts["hours"] * 3_600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def authorize(client_secret_path: Path, token_path: Path) -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover - installation guard
        raise RuntimeError("Google OAuth dependencies are not installed.") from exc
    if not client_secret_path.exists():
        raise FileNotFoundError(f"OAuth client JSON not found: {client_secret_path}")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secret_path),
        [YOUTUBE_READONLY_SCOPE],
    )
    credentials = flow.run_local_server(port=0, prompt="consent")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")


def build_youtube_service(token_path: Path) -> Any:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - installation guard
        raise RuntimeError("Google API dependencies are not installed.") from exc
    if not token_path.exists():
        raise FileNotFoundError(
            f"OAuth token not found: {token_path}. Run `youtube-digest auth`."
        )
    credentials = Credentials.from_authorized_user_file(
        str(token_path),
        [YOUTUBE_READONLY_SCOPE],
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise RuntimeError("Google OAuth credentials are invalid; re-run `youtube-digest auth`.")
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


class YouTubeDiscovery:
    def __init__(self, service: Any, storage: Storage, logger: Any) -> None:
        self.service = service
        self.storage = storage
        self.logger = logger

    def _subscriptions(self) -> list[dict[str, str]]:
        subscriptions: list[dict[str, str]] = []
        token: str | None = None
        while True:
            request = self.service.subscriptions().list(
                part="snippet",
                mine=True,
                maxResults=50,
                pageToken=token,
            )
            response = request.execute()
            for item in response.get("items", []):
                snippet = item["snippet"]
                subscriptions.append(
                    {
                        "channel_id": snippet["resourceId"]["channelId"],
                        "title": snippet.get("title", ""),
                    }
                )
            token = response.get("nextPageToken")
            if not token:
                return subscriptions

    def _resolve_upload_playlists(
        self, subscriptions: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        missing: list[dict[str, str]] = []
        resolved: list[dict[str, str]] = []
        for subscription in subscriptions:
            cached = self.storage.get_channel(subscription["channel_id"])
            if cached:
                resolved.append(
                    {
                        **subscription,
                        "uploads_playlist_id": cached["uploads_playlist_id"],
                    }
                )
            else:
                missing.append(subscription)

        for offset in range(0, len(missing), 50):
            batch = missing[offset : offset + 50]
            response = (
                self.service.channels()
                .list(
                    part="snippet,contentDetails",
                    id=",".join(item["channel_id"] for item in batch),
                    maxResults=50,
                )
                .execute()
            )
            for item in response.get("items", []):
                channel_id = item["id"]
                title = item.get("snippet", {}).get("title", "")
                uploads_id = (
                    item.get("contentDetails", {})
                    .get("relatedPlaylists", {})
                    .get("uploads")
                )
                if not uploads_id:
                    continue
                self.storage.upsert_channel(channel_id, title, uploads_id)
                resolved.append(
                    {
                        "channel_id": channel_id,
                        "title": title,
                        "uploads_playlist_id": uploads_id,
                    }
                )
        self.storage.commit()
        return resolved

    def _playlist_videos(
        self, channel: dict[str, str], since_at: datetime
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        token: str | None = None
        exhausted = False
        while not exhausted:
            response = (
                self.service.playlistItems()
                .list(
                    part="snippet,contentDetails",
                    playlistId=channel["uploads_playlist_id"],
                    maxResults=50,
                    pageToken=token,
                )
                .execute()
            )
            for item in response.get("items", []):
                snippet = item.get("snippet", {})
                content = item.get("contentDetails", {})
                video_id = content.get("videoId") or snippet.get("resourceId", {}).get(
                    "videoId"
                )
                published_raw = content.get("videoPublishedAt") or snippet.get("publishedAt")
                if not video_id or not published_raw:
                    continue
                published = parse_youtube_datetime(published_raw)
                if published < since_at:
                    exhausted = True
                    continue
                found.append(
                    {
                        "video_id": video_id,
                        "channel_id": channel["channel_id"],
                        "channel_title": channel["title"],
                        "title": snippet.get("title", ""),
                        "description": snippet.get("description", ""),
                        "published_at": published.isoformat(),
                        "duration_seconds": None,
                        "url": VIDEO_URL.format(video_id=video_id),
                    }
                )
            token = response.get("nextPageToken")
            if exhausted or not token:
                break
        return found

    def _add_video_details(self, videos: list[dict[str, Any]]) -> None:
        by_id = {video["video_id"]: video for video in videos}
        ids = list(by_id)
        for offset in range(0, len(ids), 50):
            response = (
                self.service.videos()
                .list(
                    part="snippet,contentDetails",
                    id=",".join(ids[offset : offset + 50]),
                    maxResults=50,
                )
                .execute()
            )
            for item in response.get("items", []):
                target = by_id.get(item["id"])
                if not target:
                    continue
                snippet = item.get("snippet", {})
                target["title"] = snippet.get("title", target["title"])
                target["description"] = snippet.get("description", target["description"])
                target["channel_title"] = snippet.get(
                    "channelTitle", target["channel_title"]
                )
                target["duration_seconds"] = parse_iso8601_duration(
                    item.get("contentDetails", {}).get("duration")
                )

    def discover(self, since_at: datetime, run_id: str) -> list[str]:
        subscriptions = self._subscriptions()
        self.logger.info("Resolved %s YouTube subscriptions", len(subscriptions))
        channels = self._resolve_upload_playlists(subscriptions)
        videos: list[dict[str, Any]] = []
        for channel in channels:
            try:
                videos.extend(self._playlist_videos(channel, since_at))
            except Exception:
                self.logger.exception(
                    "Failed to inspect uploads for channel %s", channel["channel_id"]
                )
        deduplicated = list({video["video_id"]: video for video in videos}.values())
        self._add_video_details(deduplicated)
        new_count = 0
        for video in deduplicated:
            new_count += int(self.storage.upsert_video(video, run_id))
        self.storage.commit()
        self.logger.info(
            "Discovered %s videos in range (%s new)", len(deduplicated), new_count
        )
        return [video["video_id"] for video in deduplicated]
