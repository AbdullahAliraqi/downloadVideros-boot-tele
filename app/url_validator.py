from urllib.parse import urlparse

SUPPORTED_DOMAINS = {
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "facebook.com",
    "fb.watch",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "reddit.com",
    "redd.it",
    "v.redd.it",
}


def normalize_host(host: str) -> str:
    host = host.lower().strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def is_supported_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    host = normalize_host(parsed.hostname or "")
    return any(host == d or host.endswith("." + d) for d in SUPPORTED_DOMAINS)


def platform_for_url(url: str) -> str | None:
    try:
        host = normalize_host(urlparse(url.strip()).hostname or "")
    except ValueError:
        return None

    if host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com"):
        return "YouTube"
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "Instagram"
    if host == "facebook.com" or host.endswith(".facebook.com") or host == "fb.watch":
        return "Facebook"
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "TikTok"
    if host in {"x.com", "twitter.com"} or host.endswith(".x.com") or host.endswith(".twitter.com"):
        return "X"
    if host == "reddit.com" or host.endswith(".reddit.com") or host == "redd.it" or host == "v.redd.it":
        return "Reddit"
    return None


def is_reddit_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return (
        host == "reddit.com"
        or host.endswith(".reddit.com")
        or host == "redd.it"
    )
