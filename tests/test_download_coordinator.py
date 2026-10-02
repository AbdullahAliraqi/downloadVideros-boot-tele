from unittest.mock import Mock

from app.download_coordinator import VideoDownloadCoordinator
from app.download_engine import DownloadResult
from app.media_tools import MediaProbeResult
from app.youtube_companion import YouTubeCompanionBlockedError
from app.video_analyzer import FormatCandidate


def fc(format_id, height=None, vcodec=None, acodec=None, filesize=None, abr=None):
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
    path = __import__("pathlib").Path(f"C:/tmp/{height}.mp4")
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
    assert downloader.download.call_count == 0
    assert gateway.download.call_count == 2
    assert outcome.result.target_height == 720


def test_youtube_companion_failure_falls_back_to_native_once():
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
