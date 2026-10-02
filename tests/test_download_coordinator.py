from pathlib import Path
from unittest.mock import Mock

import pytest

from app.download_coordinator import VideoDownloadCoordinator
from app.download_engine import DownloadResult
from app.media_tools import MediaProbeResult
from app.youtube_companion import (
    YouTubeCompanionBlockedError,
    YouTubeCompanionConfigurationError,
)
from app.video_analyzer import FormatCandidate


def fc(
    format_id,
    height=None,
    vcodec=None,
    acodec=None,
    filesize=None,
    abr=None,
):
    return FormatCandidate(
        format_id=format_id,
        height=height,
        has_video=bool(vcodec),
        has_audio=bool(acodec),
        ext="mp4",
        filesize=filesize,
        filesize_approx=None,
        vbr=None,
        abr=abr,
        tbr=None,
    )


def result(height: int, size: int) -> DownloadResult:
    path = Path(f"C:/tmp/{height}.mp4")
    return DownloadResult(
        job_id="job-1",
        file_path=path,
        target_height=height,
        selected_format=f"v{height}+a128",
        estimated_size=None,
        actual_size=size,
        exceeds_planning_limit=size > 2000 * 1024 * 1024,
        probe=MediaProbeResult(path, size, 10.0),
    )


def base_analysis():
    return {
        "title": "fallback test",
        "duration": 300,
        "formats": [
            fc("v1080", 1080, "avc1", filesize=1500 * 1024 * 1024),
            fc("v720", 720, "avc1", filesize=1200 * 1024 * 1024),
            fc("v480", 480, "avc1", filesize=900 * 1024 * 1024),
            fc("a128", acodec="mp4a", filesize=5 * 1024 * 1024, abr=128),
        ],
    }


def test_actual_oversize_1080_falls_back_to_720():
    analyzer = Mock()
    analyzer.analyze.return_value = base_analysis()
    downloader = Mock()
    downloader.download.side_effect = [
        result(1080, 2100 * 1024 * 1024),
        result(720, 1800 * 1024 * 1024),
    ]

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    outcome = coordinator.download("https://example.com/video", job_id="job-1")

    assert outcome.attempted_heights == (1080, 720)
    assert outcome.available_heights == (1080, 720, 480)
    assert outcome.fallback_count == 1
    assert outcome.result.target_height == 720
    assert outcome.result.actual_size == 1800 * 1024 * 1024
    assert downloader.download.call_count == 2


def test_actual_oversize_720_falls_back_to_480():
    analyzer = Mock()
    analyzer.analyze.return_value = base_analysis()
    downloader = Mock()
    downloader.download.side_effect = [
        result(1080, 2100 * 1024 * 1024),
        result(720, 2050 * 1024 * 1024),
        result(480, 1800 * 1024 * 1024),
    ]

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    outcome = coordinator.download("https://example.com/video", job_id="job-2")

    assert outcome.attempted_heights == (1080, 720, 480)
    assert outcome.available_heights == (1080, 720, 480)
    assert outcome.fallback_count == 2
    assert outcome.result.target_height == 480
    assert downloader.download.call_count == 3


def test_skips_unsupported_720_and_falls_directly_from_1080_to_480():
    analyzer = Mock()
    analyzer.analyze.return_value = {
        "title": "fallback test",
        "duration": 300,
        "formats": [
            fc("v1080", 1080, "avc1", filesize=1500 * 1024 * 1024),
            fc("v480", 480, "avc1", filesize=900 * 1024 * 1024),
            fc("a128", acodec="mp4a", filesize=5 * 1024 * 1024, abr=128),
        ],
    }
    downloader = Mock()
    downloader.download.side_effect = [
        result(1080, 2100 * 1024 * 1024),
        result(480, 1800 * 1024 * 1024),
    ]

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    outcome = coordinator.download("https://example.com/video", job_id="job-3")

    assert outcome.available_heights == (1080, 480)
    assert outcome.attempted_heights == (1080, 480)
    assert outcome.result.target_height == 480


def test_480_remains_final_when_actual_size_still_exceeds_limit():
    analyzer = Mock()
    analyzer.analyze.return_value = {
        "title": "fallback test",
        "duration": 300,
        "formats": [
            fc("v480", 480, "avc1", filesize=2400 * 1024 * 1024),
            fc("a128", acodec="mp4a", filesize=5 * 1024 * 1024, abr=128),
        ],
    }
    downloader = Mock()
    downloader.download.return_value = result(480, 2100 * 1024 * 1024)

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    outcome = coordinator.download("https://example.com/video", job_id="job-4")

    assert outcome.attempted_heights == (480,)
    assert outcome.available_heights == (480,)
    assert outcome.result.target_height == 480
    assert outcome.result.exceeds_planning_limit is True
    downloader.download.assert_called_once()


def test_non_youtube_uses_native_pipeline():
    analyzer = Mock()
    analyzer.analyze.return_value = base_analysis()
    downloader = Mock()
    downloader.download.return_value = result(1080, 150 * 1024 * 1024)

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    outcome = coordinator.download("https://example.com/video", job_id="native-1")

    assert outcome.available_heights == (1080, 720, 480)
    assert outcome.attempted_heights == (1080,)
    assert outcome.result.target_height == 1080
    analyzer.analyze.assert_called_once_with("https://example.com/video")
    downloader.download.assert_called_once()


def test_youtube_companion_path_handles_quality_fallback_without_native():
    gateway = Mock()
    gateway.resolve.return_value = Mock(available_heights=(1080, 720, 480))
    gateway.download.side_effect = [
        result(1080, 2100 * 1024 * 1024),
        result(720, 1800 * 1024 * 1024),
    ]
    analyzer = Mock()
    downloader = Mock()

    coordinator = VideoDownloadCoordinator(
        analyzer=analyzer,
        downloader=downloader,
        youtube_gateway=gateway,
    )
    outcome = coordinator.download(
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
        job_id="youtube-1",
    )

    assert outcome.attempted_heights == (1080, 720)
    assert outcome.available_heights == (1080, 720, 480)
    assert gateway.download.call_count == 2
    assert downloader.download.call_count == 0
    assert analyzer.analyze.call_count == 0
    assert outcome.result.target_height == 720


def test_youtube_companion_block_falls_back_to_native_once():
    gateway = Mock()
    gateway.resolve.side_effect = YouTubeCompanionBlockedError("bot check")
    analyzer = Mock()
    analyzer.analyze.return_value = base_analysis()
    downloader = Mock()
    downloader.download.return_value = result(1080, 100 * 1024 * 1024)

    coordinator = VideoDownloadCoordinator(
        analyzer=analyzer,
        downloader=downloader,
        youtube_gateway=gateway,
    )
    outcome = coordinator.download(
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
        job_id="youtube-2",
    )

    assert outcome.result.target_height == 1080
    analyzer.analyze.assert_called_once()
    downloader.download.assert_called_once()


def test_youtube_companion_configuration_error_does_not_hide_failure():
    gateway = Mock()
    gateway.resolve.side_effect = YouTubeCompanionConfigurationError("bad secret")
    analyzer = Mock()
    downloader = Mock()

    coordinator = VideoDownloadCoordinator(
        analyzer=analyzer,
        downloader=downloader,
        youtube_gateway=gateway,
    )

    with pytest.raises(YouTubeCompanionConfigurationError, match="bad secret"):
        coordinator.download(
            "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
            job_id="youtube-config",
        )

    analyzer.analyze.assert_not_called()
    downloader.download.assert_not_called()
