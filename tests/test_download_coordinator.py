from pathlib import Path
from unittest.mock import Mock

from app.download_coordinator import VideoDownloadCoordinator
from app.download_engine import DownloadResult
from app.media_tools import MediaProbeResult
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
        exceeds_planning_limit=size > 50 * 1024 * 1024,
        probe=MediaProbeResult(path, size, 10.0),
    )


def base_analysis():
    return {
        "title": "fallback test",
        "duration": 300,
        "formats": [
            fc("v1080", 1080, "avc1", filesize=40 * 1024 * 1024),
            fc("v720", 720, "avc1", filesize=30 * 1024 * 1024),
            fc("v480", 480, "avc1", filesize=20 * 1024 * 1024),
            fc("a128", acodec="mp4a", filesize=5 * 1024 * 1024, abr=128),
        ],
    }


def test_actual_oversize_1080_falls_back_to_720():
    analyzer = Mock()
    analyzer.analyze.return_value = base_analysis()
    downloader = Mock()
    downloader.download.side_effect = [
        result(1080, 60 * 1024 * 1024),
        result(720, 40 * 1024 * 1024),
    ]

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    outcome = coordinator.download("https://www.youtube.com/watch?v=abc", job_id="job-1")

    assert outcome.attempted_heights == (1080, 720)
    assert outcome.available_heights == (1080, 720, 480)
    assert outcome.fallback_count == 1
    assert outcome.result.target_height == 720
    assert outcome.result.actual_size == 40 * 1024 * 1024
    assert downloader.download.call_count == 2


def test_actual_oversize_720_falls_back_to_480():
    analyzer = Mock()
    analyzer.analyze.return_value = base_analysis()
    downloader = Mock()
    downloader.download.side_effect = [
        result(1080, 60 * 1024 * 1024),
        result(720, 55 * 1024 * 1024),
        result(480, 40 * 1024 * 1024),
    ]

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    outcome = coordinator.download("https://www.youtube.com/watch?v=abc", job_id="job-2")

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
            fc("v1080", 1080, "avc1", filesize=40 * 1024 * 1024),
            fc("v480", 480, "avc1", filesize=20 * 1024 * 1024),
            fc("a128", acodec="mp4a", filesize=5 * 1024 * 1024, abr=128),
        ],
    }
    downloader = Mock()
    downloader.download.side_effect = [
        result(1080, 60 * 1024 * 1024),
        result(480, 40 * 1024 * 1024),
    ]

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    outcome = coordinator.download("https://www.youtube.com/watch?v=abc", job_id="job-3")

    assert outcome.available_heights == (1080, 480)
    assert outcome.attempted_heights == (1080, 480)
    assert outcome.result.target_height == 480


def test_480_is_final_when_actual_size_still_exceeds_telegram_limit():
    analyzer = Mock()
    analyzer.analyze.return_value = {
        "title": "fallback test",
        "duration": 300,
        "formats": [
            fc("v480", 480, "avc1", filesize=60 * 1024 * 1024),
            fc("a128", acodec="mp4a", filesize=5 * 1024 * 1024, abr=128),
        ],
    }
    downloader = Mock()
    downloader.download.return_value = result(480, 55 * 1024 * 1024)

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    outcome = coordinator.download("https://www.youtube.com/watch?v=abc", job_id="job-4")

    assert outcome.attempted_heights == (480,)
    assert outcome.available_heights == (480,)
    assert outcome.result.target_height == 480
    assert outcome.result.exceeds_planning_limit is True
    downloader.download.assert_called_once()


def test_all_supported_platforms_use_native_yt_dlp_pipeline():
    analyzer = Mock()
    analyzer.analyze.return_value = base_analysis()
    downloader = Mock()
    downloader.download.return_value = result(1080, 40 * 1024 * 1024)

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    for url in (
        "https://www.youtube.com/watch?v=abc",
        "https://www.facebook.com/watch/?v=abc",
        "https://www.instagram.com/reel/abc/",
        "https://www.tiktok.com/@user/video/123",
        "https://x.com/user/status/123",
        "https://www.reddit.com/r/test/comments/abc/title/",
    ):
        outcome = coordinator.download(url, job_id="job-native")
        assert outcome.result.target_height == 1080

    assert analyzer.analyze.call_count == 6
    assert downloader.download.call_count == 6
