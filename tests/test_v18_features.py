from unittest.mock import Mock

from app.main import START_MENU, SUPPORTED_PLATFORMS_TEXT
from app.reddit_support import RedditResolvedVideo, RedditVariant
from app.url_validator import is_supported_url, platform_for_url


def test_six_supported_platforms_are_accepted():
    urls = {
        "YouTube": "https://www.youtube.com/watch?v=abc",
        "Facebook": "https://www.facebook.com/watch/?v=abc",
        "Instagram": "https://www.instagram.com/reel/abc/",
        "TikTok": "https://www.tiktok.com/@user/video/123",
        "X": "https://x.com/user/status/123",
        "Reddit": "https://www.reddit.com/r/test/comments/abc/title/",
    }
    for platform, url in urls.items():
        assert is_supported_url(url)
        assert platform_for_url(url) == platform


def test_start_button_is_visible_and_platform_text_lists_reddit():
    assert any(
        button.get("text") == "🏠 Start"
        for row in START_MENU["keyboard"]
        for button in row
    )
    assert "Reddit" in SUPPORTED_PLATFORMS_TEXT


def test_reddit_resolution_selection():
    resolved = RedditResolvedVideo(
        title="test",
        duration_seconds=10,
        variants=(
            RedditVariant(1080, 1920, "https://v.redd.it/id/DASH_1080.mp4"),
            RedditVariant(720, 1280, "https://v.redd.it/id/DASH_720.mp4"),
            RedditVariant(480, 854, "https://v.redd.it/id/DASH_480.mp4"),
        ),
        audio_url="https://v.redd.it/id/DASH_AUDIO_128.mp4",
    )

    assert resolved.available_heights == (1080, 720, 480)
    assert resolved.variant_for(1080).url.endswith("DASH_1080.mp4")
    assert resolved.variant_for(720).url.endswith("DASH_720.mp4")
    assert resolved.variant_for(480).url.endswith("DASH_480.mp4")
