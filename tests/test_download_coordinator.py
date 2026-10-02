from unittest.mock import Mock

from app.alldl_support import AllDLMedia, AllDLQuality
from app.download_coordinator import VideoDownloadCoordinator
from app.download_engine import DownloadResult
from app.media_tools import MediaProbeResult
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


def alldl_media():
    return AllDLMedia(
        title="Test",
        platform="YouTube",
        video_url="https://example.com/video.mp4",
        qualities=(
            AllDLQuality(1080, "https://example.com/1080.mp4"),
            AllDLQuality(720, "https://example.com/720.mp4"),
            AllDLQuality(480, "https://example.com/480.mp4"),
        ),
    )


def test_alldl_prefers_1080_and_falls_back_by_real_size():
    resolver = Mock()
    resolver.resolve.return_value = alldl_media()
    downloader = Mock()
    downloader.download.side_effect = [
        result(1080, 2100 * 1024 * 1024),
        result(720, 1800 * 1024 * 1024),
    ]

    coordinator = VideoDownloadCoordinator(
        alldl_resolver=resolver,
        alldl_downloader=downloader,
    )
    outcome = coordinator.download(
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
        job_id="alldl-1",
    )

    assert outcome.available_heights == (1080, 720, 480)
    assert outcome.attempted_heights == (1080, 720)
    assert outcome.result.target_height == 720
    assert outcome.fallback_count == 1
    downloader.download.assert_any_call(
        alldl_media(),
        1080,
        job_id="alldl-1",
    )
    downloader.download.assert_any_call(
        alldl_media(),
        720,
        job_id="alldl-1",
    )


def test_alldl_path_is_used_for_instagram():
    resolver = Mock()
    resolver.resolve.return_value = alldl_media()
    downloader = Mock()
    downloader.download.return_value = result(720, 100 * 1024 * 1024)

    native_analyzer = Mock()
    native_downloader = Mock()

    coordinator = VideoDownloadCoordinator(
        analyzer=native_analyzer,
        downloader=native_downloader,
        alldl_resolver=resolver,
        alldl_downloader=downloader,
    )
    outcome = coordinator.download(
        "https://www.instagram.com/reel/example/",
        job_id="alldl-2",
    )

    assert outcome.result.target_height == 720
    native_analyzer.analyze.assert_not_called()
    native_downloader.download.assert_not_called()


def test_alldl_failure_falls_back_to_native_pipeline():
    resolver = Mock()
    resolver.resolve.side_effect = RuntimeError("api failed")
    native_analyzer = Mock()
    native_analyzer.analyze.return_value = base_analysis()
    native_downloader = Mock()
    native_downloader.download.return_value = result(1080, 100 * 1024 * 1024)

    coordinator = VideoDownloadCoordinator(
        analyzer=native_analyzer,
        downloader=native_downloader,
        alldl_resolver=resolver,
    )
    outcome = coordinator.download(
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
        job_id="alldl-3",
    )

    assert outcome.result.target_height == 1080
    native_analyzer.analyze.assert_called_once()
    native_downloader.download.assert_called_once()
