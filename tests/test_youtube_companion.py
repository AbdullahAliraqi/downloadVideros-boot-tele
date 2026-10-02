from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.config import settings
from app.media_tools import MediaProbeResult
from app.youtube_companion import (
    YouTubeCompanionBlockedError,
    YouTubeCompanionGateway,
    YouTubeResolvedVideo,
    YouTubeStream,
    extract_youtube_video_id,
)


def test_extracts_youtube_ids():
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=aqz-KE-bpKQ") == "aqz-KE-bpKQ"
    assert extract_youtube_video_id("https://youtube.com/shorts/pOj_k8_svi8") == "pOj_k8_svi8"
    assert extract_youtube_video_id("https://youtu.be/aqz-KE-bpKQ?t=3") == "aqz-KE-bpKQ"


def test_resolved_video_selects_best_complete_mp4_targets():
    resolved = YouTubeResolvedVideo(
        video_id="abc123",
        title="Example",
        duration_seconds=30,
        streams=(
            YouTubeStream(137, 1920, 1080, "video/mp4", 5000000, True, False, 100),
            YouTubeStream(136, 1280, 720, "video/mp4", 2500000, True, False, 80),
            YouTubeStream(135, 854, 480, "video/mp4", 1000000, True, False, 40),
            YouTubeStream(140, None, None, "audio/mp4", 130000, False, True, 10),
            YouTubeStream(22, 1280, 720, "video/mp4", 2000000, True, True, 90),
        ),
    )

    assert resolved.available_heights == (1080, 720, 480)
    assert resolved.best_video(1080).itag == 137
    assert resolved.best_video(720).itag == 136
    assert resolved.best_audio().itag == 140


def test_resolved_video_supports_portrait_1080():
    resolved = YouTubeResolvedVideo(
        video_id="short1",
        title="Portrait",
        duration_seconds=15,
        streams=(
            YouTubeStream(999, 1080, 1920, "video/mp4", 3000000, True, False, 100),
            YouTubeStream(140, None, None, "audio/mp4", 130000, False, True, 10),
        ),
    )
    assert resolved.available_heights == (1080,)
    assert resolved.best_video(1080).itag == 999


def test_player_request_uses_companion_bearer_key():
    gateway = YouTubeCompanionGateway(
        base_url="http://youtube-companion:8282/companion",
        secret_key="A1b2C3d4E5f6G7h8",
    )
    response = Mock(status_code=200)
    response.json.return_value = {
        "playabilityStatus": {"status": "OK"},
        "videoDetails": {"title": "Example", "lengthSeconds": "30"},
        "streamingData": {
            "formats": [],
            "adaptiveFormats": [
                {
                    "itag": 137,
                    "mimeType": "video/mp4; codecs=\"avc1\"",
                    "width": 1920,
                    "height": 1080,
                    "bitrate": 5000000,
                },
                {
                    "itag": 140,
                    "mimeType": "audio/mp4; codecs=\"mp4a\"",
                    "bitrate": 130000,
                },
            ],
        },
    }

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=None)
    client.post.return_value = response

    with patch("app.youtube_companion.httpx.Client", return_value=client):
        resolved = gateway.resolve("https://www.youtube.com/watch?v=aqz-KE-bpKQ")

    assert resolved.video_id == "aqz-KE-bpKQ"
    assert resolved.available_heights == (1080,)
    client.post.assert_called_once_with(
        "http://youtube-companion:8282/companion/youtubei/v1/player",
        json={"videoId": "aqz-KE-bpKQ"},
    )


def test_player_reports_youtube_bot_block():
    gateway = YouTubeCompanionGateway(
        base_url="http://youtube-companion:8282/companion",
        secret_key="A1b2C3d4E5f6G7h8",
    )
    response = Mock(status_code=200)
    response.json.return_value = {
        "playabilityStatus": {
            "status": "LOGIN_REQUIRED",
            "reason": "Sign in to confirm you're not a bot.",
        }
    }
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=None)
    client.post.return_value = response

    with patch("app.youtube_companion.httpx.Client", return_value=client):
        with pytest.raises(YouTubeCompanionBlockedError):
            gateway.resolve("https://www.youtube.com/watch?v=aqz-KE-bpKQ")


def test_companion_download_uses_latest_version_and_probes_output(tmp_path):
    gateway = YouTubeCompanionGateway(
        base_url="http://youtube-companion:8282/companion",
        secret_key="A1b2C3d4E5f6G7h8",
    )
    resolved = YouTubeResolvedVideo(
        video_id="abc123",
        title="Example",
        duration_seconds=10,
        streams=(
            YouTubeStream(22, 1280, 720, "video/mp4", 2000000, True, True, 100),
        ),
    )

    class StreamResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size=1024 * 1024):
            yield b"video-bytes"

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=None)
    client.stream.return_value = StreamResponse()

    probe = MediaProbeResult(
        Path(tmp_path / "unused"),
        len(b"video-bytes"),
        10.0,
        1280,
        720,
    )

    with patch("app.youtube_companion.httpx.Client", return_value=client), \
         patch("app.youtube_companion.FFmpegTools.check"), \
         patch("app.youtube_companion.FFmpegTools.probe", return_value=probe):
        with patch.object(settings, "download_root", str(tmp_path)):
            result = gateway.download(resolved, 720, job_id="job-1")

    assert result.target_height == 720
    assert result.actual_size == len(b"video-bytes")
    assert (tmp_path / "job-1" / "abc123_720p.mp4").read_bytes() == b"video-bytes"
    client.stream.assert_called_once()
    _, kwargs = client.stream.call_args
    assert kwargs["params"]["id"] == "abc123"
    assert kwargs["params"]["itag"] == "22"
    assert kwargs["params"]["local"] == "true"


def test_invalid_companion_secret_is_rejected():
    gateway = YouTubeCompanionGateway(
        base_url="http://youtube-companion:8282/companion",
        secret_key="too-short",
    )
    with pytest.raises(Exception, match="exactly 16 characters"):
        gateway.resolve("https://www.youtube.com/watch?v=abc123")
