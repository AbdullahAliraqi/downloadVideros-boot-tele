from __future__ import annotations

from urllib.parse import urlparse

from .config import settings, valid_cookiefile

TELEGRAM_MAX_FILESIZE = 50 * 1024 * 1024

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/154.0.0.0 Safari/537.36"
)

BASE_HTTP_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept": "*/*",
}

YOUTUBE_FALLBACK_PROFILES = (
    ("web", ("web",), True),
    ("android_vr", ("android_vr",), False),
    ("web_embedded", ("web_embedded",), True),
)


def platform_for_host(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host == "youtube.com" or host.endswith(".youtube.com") or host == "youtu.be":
        return "YouTube"
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "Instagram"
    if host == "facebook.com" or host.endswith(".facebook.com") or host == "fb.watch":
        return "Facebook"
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "TikTok"
    if host in {"x.com", "twitter.com"} or host.endswith(".x.com") or host.endswith(".twitter.com"):
        return "X"
    if host == "reddit.com" or host.endswith(".reddit.com") or host in {"redd.it", "v.redd.it"}:
        return "Reddit"
    return None


def _referer_for(platform: str | None) -> str | None:
    return {
        "YouTube": "https://www.youtube.com/",
        "Instagram": "https://www.instagram.com/",
        "TikTok": "https://www.tiktok.com/",
        "X": "https://x.com/",
        "Facebook": "https://www.facebook.com/",
        "Reddit": "https://www.reddit.com/",
    }.get(platform)


def build_ydl_opts(
    url: str,
    *,
    output_template: str | None = None,
    format_selector: str | None = None,
    skip_download: bool = False,
    youtube_clients: tuple[str, ...] | None = None,
    use_cookies: bool = True,
) -> dict:
    platform = platform_for_host(url)
    headers = dict(BASE_HTTP_HEADERS)
    referer = _referer_for(platform)
    if referer:
        headers["Referer"] = referer

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "overwrites": True,
        "http_headers": headers,
        "max_filesize": TELEGRAM_MAX_FILESIZE,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 1,
        "sleep_interval_requests": 1,
    }

    if skip_download:
        options["skip_download"] = True

    if output_template:
        options["outtmpl"] = output_template

    if format_selector:
        options["format"] = format_selector

    if platform == "YouTube":
        clients = youtube_clients or ("web", "android_vr")
        options["extractor_args"] = {
            "youtube": {
                "player_client": list(clients),
            }
        }

        cookiefile = valid_cookiefile(settings.ytdlp_cookies_file)
        if use_cookies and cookiefile:
            options["cookiefile"] = cookiefile
    else:
        cookiefile = valid_cookiefile(settings.ytdlp_cookies_file)
        if use_cookies and cookiefile:
            options["cookiefile"] = cookiefile

    proxy = settings.youtube_proxy_url if platform == "YouTube" else settings.ytdlp_proxy_url
    if proxy:
        options["proxy"] = proxy

    return options
