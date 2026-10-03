from unittest.mock import patch

from app.config import settings
from app.ydl_config import TELEGRAM_MAX_FILESIZE, build_ydl_opts


def test_youtube_options_use_browser_headers_and_lightweight_clients(tmp_path):
    cookiefile = tmp_path / "cookies.txt"
    cookiefile.write_text("# Netscape HTTP Cookie File\n")

    with patch.object(settings, "ytdlp_cookies_file", str(cookiefile)):
        options = build_ydl_opts(
            "https://youtube.com/shorts/abc123",
            skip_download=True,
        )

    assert options["cookiefile"] == str(cookiefile)
    assert options["http_headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert options["http_headers"]["Accept-Language"] == "en-US,en;q=0.9,ar;q=0.8"
    assert options["extractor_args"]["youtube"]["player_client"] == ["web", "android_vr"]
    assert options["max_filesize"] == TELEGRAM_MAX_FILESIZE == 50 * 1024 * 1024
    assert options["concurrent_fragment_downloads"] == 1


def test_android_vr_profile_can_be_used_without_account_cookies(tmp_path):
    cookiefile = tmp_path / "cookies.txt"
    cookiefile.write_text("# Netscape HTTP Cookie File\n")

    with patch.object(settings, "ytdlp_cookies_file", str(cookiefile)):
        options = build_ydl_opts(
            "https://youtube.com/watch?v=abc123",
            youtube_clients=("android_vr",),
            use_cookies=False,
        )

    assert options["extractor_args"]["youtube"]["player_client"] == ["android_vr"]
    assert "cookiefile" not in options


def test_non_youtube_platforms_get_common_browser_headers_and_referer():
    options = build_ydl_opts("https://www.instagram.com/reel/abc123/")

    assert options["http_headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert options["http_headers"]["Accept-Language"] == "en-US,en;q=0.9,ar;q=0.8"
    assert options["http_headers"]["Referer"] == "https://www.instagram.com/"
    assert "extractor_args" not in options
