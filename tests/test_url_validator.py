from app.url_validator import is_supported_url


def test_supported_domains():
    assert is_supported_url("https://youtube.com/watch?v=abc")
    assert is_supported_url("https://youtu.be/abc")
    assert is_supported_url("https://www.instagram.com/reel/abc/")
    assert is_supported_url("https://facebook.com/watch/?v=abc")
    assert is_supported_url("https://fb.watch/abc/")
    assert is_supported_url("https://www.tiktok.com/@user/video/123")
    assert is_supported_url("https://x.com/user/status/123")
    assert is_supported_url("https://twitter.com/user/status/123")
    assert is_supported_url("https://www.reddit.com/r/test/comments/abc/title/")
    assert is_supported_url("https://v.redd.it/abc123")


def test_unsupported_domains():
    assert not is_supported_url("https://example.com/video")
    assert not is_supported_url("ftp://youtube.com/video")
    assert not is_supported_url("not-a-url")
