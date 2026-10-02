from unittest.mock import Mock

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
    analyzer.analyze.return_value = {
        "title": "fallback test",
        "duration": 300,
        "formats": [
            fc("v1080", 1080, "avc1", filesize=1500 * 1024 * 1024),
            fc("v720", 720, "avc1", filesize=1500 * 1024 * 1024),
            fc("v480", 480, "avc1", filesize=900 * 1024 * 1024),
            fc("a128", acodec="mp4a", filesize=5 * 1024 * 1024, abr=128),
        ],
    }
    downloader = Mock()
    downloader.download.side_effect = [
        result(1080, 1500 * 1024 * 1024),
    ]

    coordinator = VideoDownloadCoordinator(analyzer=analyzer, downloader=downloader)
    outcome = coordinator.download("https://example.com/video", job_id="job-2")

    assert outcome.attempted_heights == (1080,)
    assert outcome.result.target_height == 1080


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

def test_youtube_uses_piped_backend():
    from unittest.mock import patch
    from app.youtube_api import PipedInfo

    youtube_client = Mock()
    youtube_client.inspect.return_value = PipedInfo(
        title="YouTube test",
        duration_seconds=30.0,
        available_heights=(1080, 720, 480),
        size_by_height={
            1080: 150 * 1024 * 1024,
            720: 90 * 1024 * 1024,
            480: 50 * 1024 * 1024,
        },
        instance_url="https://pipedapi.example",
    )
    youtube_client.download.return_value = result(1080, 150 * 1024 * 1024)

    coordinator = VideoDownloadCoordinator()
    coordinator.youtube_client = youtube_client

    outcome = coordinator.download(
            "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
            job_id="job-youtube",
        )

    assert outcome.available_heights == (1080, 720, 480)
    assert outcome.attempted_heights == (1080,)
    assert outcome.result.target_height == 1080
    youtube_client.inspect.assert_called_once_with("https://www.youtube.com/watch?v=aqz-KE-bpKQ")
    youtube_client.download.assert_called_once()


def test_youtube_provider_falls_back_to_alldl_when_piped_and_invidious_fail():
    from unittest.mock import patch
    from app.youtube_api import PipedYouTubeClient

    coordinator = VideoDownloadCoordinator()
    media = {
        "title": "Fallback YouTube",
        "qualities": [
            {"quality": "1080p", "url": "https://media.example/1080.mp4"},
            {"quality": "720p", "url": "https://media.example/720.mp4"},
            {"quality": "480p", "url": "https://media.example/480.mp4"},
        ],
        "videoUrl": "https://media.example/best.mp4",
    }

    with (
        patch.object(
            coordinator.youtube_client,
            "_get_payload",
            side_effect=RuntimeError("Piped unavailable"),
        ),
        patch.object(
            coordinator.youtube_client,
            "_get_invidious_payload",
            side_effect=RuntimeError("Invidious unavailable"),
        ),
        patch.object(
            PipedYouTubeClient,
            "_fetch_alldl_payload",
            return_value=media,
        ),
    ):
        info = coordinator.youtube_client.inspect(
            "https://www.youtube.com/shorts/pOj_k8_svi8"
        )

    assert info.available_heights == (1080, 720, 480)
    assert info.instance_url == "alldl:"
