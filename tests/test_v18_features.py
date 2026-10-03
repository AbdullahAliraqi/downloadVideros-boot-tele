from app.main import START_MENU, SUPPORTED_PLATFORMS_TEXT
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


def test_start_menu_contains_all_expected_actions():
    flattened = [button for row in START_MENU for button in row]
    assert "🏠 Start" in flattened
    assert "🎬 تنزيل فيديو" in flattened
    assert "🌐 المنصات المدعومة" in flattened
    assert "ℹ️ طريقة الاستخدام" in flattened
    assert "Reddit" in SUPPORTED_PLATFORMS_TEXT


def test_unknown_domain_is_not_supported():
    assert not is_supported_url("https://example.com/video")
