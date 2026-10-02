from unittest.mock import Mock, patch

from app.piped_youtube import (
    PipedAudioStream,
    PipedResolvedVideo,
    PipedUnavailableError,
    PipedVideoStream,
    PipedYoutubeResolver,
    extract_youtube_video_id,
)


def test_extract_youtube_video_id_supports_watch_and_shorts():
    assert extract_youtube_video_id(
        "https://www.youtube.com/watch?v=pOj_k8_svi8"
    ) == "pOj_k8_svi8"
    assert extract_youtube_video_id(
        "https://youtube.com/shorts/pOj_k8_svi8?si=test"
    ) == "pOj_k8_svi8"
    assert extract_youtube_video_id(
        "https://youtu.be/pOj_k8_svi8"
    ) == "pOj_k8_svi8"


def test_resolved_video_prefers_progressive_mp4():
    resolved = PipedResolvedVideo(
        video_id="abc123456",
        title="Example",
        duration_seconds=10,
        video_streams=(
            PipedVideoStream(
                1080, 1920, "https://video-only", "video/mp4", 8000000, True
            ),
            PipedVideoStream(
                1080, 1920, "https://progressive", "video/mp4", 7000000, False
            ),
            PipedVideoStream(
                720, 1280, "https://webm", "video/webm", 9000000, False
            ),
        ),
        audio_streams=(
            PipedAudioStream("https://audio", "audio/mp4", 128000),
        ),
        api_base_url="https://piped.example",
    )

    selected = resolved.video_for(1080)

    assert selected is not None
    assert selected.url == "https://progressive"
    assert resolved.available_heights == (1080, 720)


def test_resolver_tries_next_piped_instance():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "title": "Example",
        "duration": 12,
        "videoStreams": [
            {
                "height": 720,
                "width": 1280,
                "url": "https://cdn.example/video.mp4",
                "mimeType": "video/mp4",
                "bitrate": 1000000,
                "videoOnly": False,
            }
        ],
        "audioStreams": [],
    }

    client = Mock()
    client.get.side_effect = [
        RuntimeError("first instance failed"),
        response,
    ]

    with patch("app.piped_youtube.httpx.Client", return_value=client):
        resolved = PipedYoutubeResolver(
            api_urls=("https://bad.example", "https://good.example"),
        ).resolve("https://www.youtube.com/shorts/pOj_k8_svi8")

    assert resolved.api_base_url == "https://good.example"
    assert resolved.available_heights == (720,)


def test_resolver_raises_when_all_instances_fail():
    client = Mock()
    client.get.side_effect = RuntimeError("unavailable")

    with patch("app.piped_youtube.httpx.Client", return_value=client):
        try:
            PipedYoutubeResolver(
                api_urls=("https://bad.example",),
            ).resolve("https://www.youtube.com/watch?v=pOj_k8_svi8")
        except PipedUnavailableError:
            pass
        else:
            raise AssertionError("Expected PipedUnavailableError")
