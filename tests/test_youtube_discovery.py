from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from youtube_digest.storage import Storage
from youtube_digest.youtube import YouTubeDiscovery


class Request:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def execute(self) -> dict[str, Any]:
        return self.payload


class Resource:
    def __init__(self, handler: Any) -> None:
        self.handler = handler

    def list(self, **kwargs: Any) -> Request:
        return Request(self.handler(kwargs))


class FakeYouTube:
    def subscriptions(self) -> Resource:
        return Resource(
            lambda _kwargs: {
                "items": [
                    {
                        "snippet": {
                            "resourceId": {"channelId": "channel-1"},
                            "title": "Macro Channel",
                        }
                    }
                ]
            }
        )

    def channels(self) -> Resource:
        return Resource(
            lambda _kwargs: {
                "items": [
                    {
                        "id": "channel-1",
                        "snippet": {"title": "Macro Channel"},
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": "uploads-1"}
                        },
                    }
                ]
            }
        )

    def playlistItems(self) -> Resource:
        return Resource(
            lambda _kwargs: {
                "items": [
                    {
                        "snippet": {
                            "title": "Fed update",
                            "description": "Rates",
                            "publishedAt": "2026-07-30T12:00:00Z",
                        },
                        "contentDetails": {
                            "videoId": "video-1",
                            "videoPublishedAt": "2026-07-30T12:00:00Z",
                        },
                    },
                    {
                        "snippet": {
                            "title": "Old",
                            "description": "",
                            "publishedAt": "2026-07-20T12:00:00Z",
                        },
                        "contentDetails": {
                            "videoId": "old-video",
                            "videoPublishedAt": "2026-07-20T12:00:00Z",
                        },
                    },
                ]
            }
        )

    def videos(self) -> Resource:
        return Resource(
            lambda _kwargs: {
                "items": [
                    {
                        "id": "video-1",
                        "snippet": {
                            "title": "Fed update",
                            "description": "Rates",
                            "channelTitle": "Macro Channel",
                        },
                        "contentDetails": {"duration": "PT15M"},
                    }
                ]
            }
        )


class Logger:
    def info(self, *_args: Any) -> None:
        pass

    def exception(self, *_args: Any) -> None:
        raise AssertionError("Discovery should not log an exception")


def test_discovery_filters_by_time_and_deduplicates(tmp_path: Path) -> None:
    with Storage(tmp_path / "state.db") as storage:
        run_id = storage.start_run(datetime(2026, 7, 30, tzinfo=UTC))
        discovery = YouTubeDiscovery(FakeYouTube(), storage, Logger())

        first = discovery.discover(datetime(2026, 7, 29, tzinfo=UTC), run_id)
        second = discovery.discover(datetime(2026, 7, 29, tzinfo=UTC), run_id)

        assert first == ["video-1"]
        assert second == ["video-1"]
        rows = storage.rows_for_ids(["video-1", "old-video"])
        assert [row["video_id"] for row in rows] == ["video-1"]
        assert rows[0]["duration_seconds"] == 900
