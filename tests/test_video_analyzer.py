from unittest.mock import patch

import pytest

from app.config import settings
from app.video_analyzer import (
    MAX_PLANNING_SIZE_BYTES,
    available_resolutions,
    build_download_plan,
)


def fmt(
    format_id,
    *,
    width=None,
    height=None,
    vcodec=None,
    acodec=None,
    filesize=None,
    filesize_approx=None,
    vbr=None,
    abr=None,
    tbr=None,
):
    return {
        "format_id": format_id,
        "width": width,
        "height": height,
        "vcodec": vcodec,
        "acodec": acodec,
        "filesize": filesize,
        "filesize_approx": filesize_approx,
        "vbr": vbr,
        "abr": abr,
        "tbr": tbr,
    }


def test_limit_is_50_mb():
    assert MAX_PLANNING_SIZE_BYTES == 50 * 1024 * 1024


def test_prefers_highest_supported_1080_even_when_estimate_exceeds_2000_mb():
    analysis = {
        "duration": 300,
        "formats": [
            fmt("v1080", height=1080, vcodec="avc1", filesize=2100 * 1024 * 1024),
            fmt("v720", height=720, vcodec="avc1", filesize=1500 * 1024 * 1024),
            fmt("v480", height=480, vcodec="avc1", filesize=900 * 1024 * 1024),
            fmt("a128", acodec="mp4a", abr=128, filesize=5 * 1024 * 1024),
        ],
    }

    plan = build_download_plan(analysis)

    assert plan.target_height == 1080
    assert plan.format_selector == "v1080+a128"
    assert plan.estimated_size == 2105 * 1024 * 1024
    assert plan.requires_size_reduction is True


def test_selects_720_when_1080_is_not_supported():
    analysis = {
        "duration": 300,
        "formats": [
            fmt("v720", height=720, vcodec="avc1", filesize=1500 * 1024 * 1024),
            fmt("v480", height=480, vcodec="avc1", filesize=900 * 1024 * 1024),
            fmt("a128", acodec="mp4a", abr=128, filesize=5 * 1024 * 1024),
        ],
    }

    assert available_resolutions(analysis) == (720, 480)
    plan = build_download_plan(analysis)
    assert plan.target_height == 720
    assert plan.format_selector == "v720+a128"


def test_supports_portrait_1080p_short():
    analysis = {
        "duration": 60,
        "formats": [
            fmt("short1080", width=1080, height=1920, vcodec="avc1", filesize=300 * 1024 * 1024),
            fmt("a128", acodec="mp4a", abr=128, filesize=5 * 1024 * 1024),
        ],
    }

    assert available_resolutions(analysis) == (1080,)
    plan = build_download_plan(analysis)
    assert plan.target_height == 1080
    assert plan.format_selector == "short1080+a128"


def test_selects_480_when_only_480_is_supported():
    analysis = {
        "duration": 300,
        "formats": [
            fmt("v480", height=480, vcodec="avc1", filesize=900 * 1024 * 1024),
            fmt("a128", acodec="mp4a", abr=128, filesize=5 * 1024 * 1024),
        ],
    }

    assert available_resolutions(analysis) == (480,)
    plan = build_download_plan(analysis)
    assert plan.target_height == 480
    assert plan.format_selector == "v480+a128"


def test_never_selects_720_when_source_does_not_have_720():
    analysis = {
        "duration": 300,
        "formats": [
            fmt("v1080", height=1080, vcodec="avc1", filesize=1900 * 1024 * 1024),
            fmt("v480", height=480, vcodec="avc1", filesize=900 * 1024 * 1024),
            fmt("a128", acodec="mp4a", abr=128, filesize=5 * 1024 * 1024),
        ],
    }

    assert available_resolutions(analysis) == (1080, 480)
    plan = build_download_plan(analysis, targets=(720, 480))
    assert plan.target_height == 480


def test_uses_exact_progressive_file_size_without_separate_audio():
    analysis = {
        "duration": 300,
        "formats": [
            fmt("p1080", height=1080, vcodec="avc1", acodec="mp4a", filesize=80 * 1024 * 1024),
        ],
    }

    plan = build_download_plan(analysis)

    assert plan.format_selector == "p1080"
    assert plan.estimated_size == 80 * 1024 * 1024
    assert plan.exact_size_known is True


def test_estimates_size_from_bitrate_when_size_fields_are_missing():
    analysis = {
        "duration": 100,
        "formats": [
            fmt("v1080", height=1080, vcodec="avc1", tbr=6000),
            fmt("a128", acodec="mp4a", abr=128),
        ],
    }

    plan = build_download_plan(analysis)

    assert plan.target_height == 1080
    assert plan.estimated_size == int((6000 + 128) * 1000 / 8 * 100)
    assert plan.exact_size_known is False


def test_analyzer_calls_yt_dlp_with_download_disabled():
    fake_info = {
        "id": "abc",
        "title": "Example",
        "duration": 12,
        "formats": [],
    }

    from app.video_analyzer import VideoMetadataAnalyzer

    with patch("app.video_analyzer.yt_dlp.YoutubeDL") as ydl_cls:
        ydl = ydl_cls.return_value.__enter__.return_value
        ydl.extract_info.return_value = fake_info

        result = VideoMetadataAnalyzer().analyze("https://example.com/video")

        ydl_cls.assert_called_once()
        opts = ydl_cls.call_args.args[0]
        assert opts["skip_download"] is True
        assert opts["noplaylist"] is True
        ydl.extract_info.assert_called_once_with("https://example.com/video", download=False)
        assert result["id"] == "abc"
        assert result["available_resolutions"] == ()

def test_analyzer_uses_configured_youtube_cookies(tmp_path):
    fake_info = {
        "id": "abc",
        "title": "Example",
        "duration": 12,
        "formats": [],
    }
    cookiefile = tmp_path / "youtube-cookies.txt"
    cookiefile.write_text("# Netscape HTTP Cookie File\\nexample\\tTRUE\\t/\\tFALSE\\t0\\tsession\\tvalue\\n")

    from app.video_analyzer import VideoMetadataAnalyzer

    with patch.object(
        settings,
        "ytdlp_cookies_file",
        str(cookiefile),
    ), patch("app.video_analyzer.yt_dlp.YoutubeDL") as ydl_cls:
        ydl = ydl_cls.return_value.__enter__.return_value
        ydl.extract_info.return_value = fake_info

        VideoMetadataAnalyzer().analyze(
            "https://www.youtube.com/watch?v=abc"
        )

        opts = ydl_cls.call_args.args[0]
        assert opts["cookiefile"] == str(cookiefile)


def test_analyzer_prefers_youtube_specific_proxy():
    fake_info = {
        "id": "abc",
        "title": "Example",
        "duration": 12,
        "formats": [],
    }

    from app.video_analyzer import VideoMetadataAnalyzer

    with patch.object(settings, "youtube_proxy_url", "socks5://youtube-proxy"),          patch.object(settings, "ytdlp_proxy_url", "http://generic-proxy"),          patch("app.video_analyzer.yt_dlp.YoutubeDL") as ydl_cls:
        ydl = ydl_cls.return_value.__enter__.return_value
        ydl.extract_info.return_value = fake_info

        VideoMetadataAnalyzer().analyze(
            "https://www.youtube.com/watch?v=abc"
        )

        opts = ydl_cls.call_args.args[0]
        assert opts["proxy"] == "socks5://youtube-proxy"


def test_analyzer_does_not_use_companion_or_browser_runtime():
    fake_info = {
        "id": "abc",
        "title": "Example",
        "duration": 12,
        "formats": [],
    }

    from app.video_analyzer import VideoMetadataAnalyzer

    with patch("app.video_analyzer.yt_dlp.YoutubeDL") as ydl_cls:
        ydl = ydl_cls.return_value.__enter__.return_value
        ydl.extract_info.return_value = fake_info

        VideoMetadataAnalyzer().analyze("https://www.youtube.com/watch?v=abc")

        opts = ydl_cls.call_args.args[0]
        assert opts["extractor_args"]["youtube"]["player_client"] == ["web"]
        assert "js_runtimes" not in opts
        assert "impersonate" not in opts



@pytest.mark.parametrize(
    "bad_formats",
    [[], [{"format_id": "x", "height": 360, "vcodec": "avc1", "acodec": "mp4a"}]],
)
def test_raises_when_no_480_or_better_format_exists(bad_formats):
    with pytest.raises(ValueError):
        build_download_plan({"duration": 60, "formats": bad_formats})


def test_analyzer_ignores_invalid_cookie_file(tmp_path):
    from app.video_analyzer import VideoMetadataAnalyzer

    cookiefile = tmp_path / "invalid-cookies.txt"
    cookiefile.write_text("not-a-cookie-jar\n")

    fake_info = {
        "id": "abc",
        "title": "Example",
        "duration": 12,
        "formats": [],
    }

    with patch.object(settings, "ytdlp_cookies_file", str(cookiefile)), \
         patch("app.video_analyzer.yt_dlp.YoutubeDL") as ydl_cls:
        ydl = ydl_cls.return_value.__enter__.return_value
        ydl.extract_info.return_value = fake_info

        VideoMetadataAnalyzer().analyze("https://www.youtube.com/watch?v=abc")

        opts = ydl_cls.call_args.args[0]
        assert "cookiefile" not in opts


def test_analyzer_accepts_netscape_cookie_header(tmp_path):
    from app.video_analyzer import VideoMetadataAnalyzer

    cookiefile = tmp_path / "cookies.txt"
    cookiefile.write_text("# Netscape HTTP Cookie File\n")

    fake_info = {
        "id": "abc",
        "title": "Example",
        "duration": 12,
        "formats": [],
    }

    with patch.object(settings, "ytdlp_cookies_file", str(cookiefile)), \
         patch("app.video_analyzer.yt_dlp.YoutubeDL") as ydl_cls:
        ydl = ydl_cls.return_value.__enter__.return_value
        ydl.extract_info.return_value = fake_info

        VideoMetadataAnalyzer().analyze("https://www.youtube.com/watch?v=abc")

        opts = ydl_cls.call_args.args[0]
        assert opts["cookiefile"] == str(cookiefile)
