from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree import ElementTree as ET

import httpx

from .config import settings
from .download_engine import DownloadResult
from .media_tools import FFmpegTools
from .video_analyzer import TARGET_RESOLUTIONS

import yt_dlp

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36"
)


@dataclass(frozen=True)
class RedditVariant:
    height: int
    width: int | None
    url: str
    format_id: str | None = None
    has_audio: bool = False


@dataclass(frozen=True)
class RedditResolvedVideo:
    title: str
    duration_seconds: float | None
    variants: tuple[RedditVariant, ...]
    audio_url: str | None
    source_url: str | None = None
    audio_format_id: str | None = None

    @property
    def available_heights(self) -> tuple[int, ...]:
        return tuple(
            target
            for target in TARGET_RESOLUTIONS
            if any(item.height == target for item in self.variants)
        )

    def variant_for(self, height: int) -> RedditVariant | None:
        matches = [item for item in self.variants if item.height == height]
        if not matches:
            return None
        return max(matches, key=lambda item: item.width or 0)


def is_reddit_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host == "reddit.com" or host.endswith(".reddit.com") or host == "redd.it"


def _json_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path.endswith(".json"):
        path += ".json"
    query = parsed.query
    if query:
        query += "&raw_json=1"
    else:
        query = "raw_json=1"
    return urlunparse(("https", "www.reddit.com", path, "", query, ""))


def _http_client() -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
            "Referer": "https://www.reddit.com/",
        },
        follow_redirects=True,
        timeout=30.0,
    )


def _walk_reddit_video(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        candidate = value.get("reddit_video")
        if isinstance(candidate, dict):
            if candidate.get("fallback_url") or candidate.get("dash_url") or candidate.get("hls_url"):
                return candidate
        for child in value.values():
            found = _walk_reddit_video(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _walk_reddit_video(child)
            if found:
                return found
    return None


def _first_text(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        for child in value.values():
            found = _first_text(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_text(child, keys)
            if found:
                return found
    return None


def _extract_json_metadata(client: httpx.Client, url: str) -> tuple[dict[str, Any] | None, str | None, float | None]:
    try:
        response = client.get(_json_url(url))
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None, None, None

    video = _walk_reddit_video(payload)
    title = _first_text(payload, ("title", "name"))
    duration = None
    if video is not None:
        raw_duration = video.get("duration")
        if isinstance(raw_duration, (int, float)):
            duration = float(raw_duration)
    return video, title, duration


def _extract_urls_from_html(html: str) -> tuple[str | None, list[tuple[int, str]], str | None]:
    # Reddit can embed JSON-escaped URLs or direct packaged-media URLs in page HTML.
    unescaped = (
        html.replace("\\/", "/")
        .replace("&amp;", "&")
        .replace("\\u0026", "&")
    )

    dash_url = None
    mpd_match = re.search(
        r"https?://(?:v\.redd\.it|packaged-media\.redd\.it)/[^\"'<>\\ ]+/DASHPlaylist\.mpd[^\"'<>\\ ]*",
        unescaped,
    )
    if mpd_match:
        dash_url = mpd_match.group(0)

    found: dict[int, str] = {}
    for match in re.finditer(
        r"https?://(?:v\.redd\.it|packaged-media\.redd\.it)/[^\"'<>\\ ]+/(?:DASH_|m2-res_)(\d+)(?:p)?(?:\.mp4|/)[^\"'<>\\ ]*",
        unescaped,
    ):
        try:
            height = int(match.group(1))
        except ValueError:
            continue
        if height in TARGET_RESOLUTIONS and height not in found:
            found[height] = match.group(0)

    fallback = None
    fallback_match = re.search(
        r"https?://(?:v\.redd\.it|packaged-media\.redd\.it)/[^\"'<>\\ ]+/(?:DASH_\d+\.mp4|m2-res_\d+p\.mp4)[^\"'<>\\ ]*",
        unescaped,
    )
    if fallback_match:
        fallback = fallback_match.group(0)

    return dash_url, sorted(found.items(), reverse=True), fallback


def _parse_mpd(client: httpx.Client, dash_url: str) -> tuple[list[RedditVariant], str | None]:
    try:
        response = client.get(dash_url)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception:
        return [], None

    variants: dict[int, RedditVariant] = {}
    audio_candidates: list[str] = []
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0] + "}"

    for representation in root.iter(f"{namespace}Representation"):
        height_raw = representation.attrib.get("height")
        width_raw = representation.attrib.get("width")
        mime = representation.attrib.get("mimeType", "")
        content_type = representation.attrib.get("contentType", "")
        base = representation.find(f"{namespace}BaseURL")
        if base is None or not base.text:
            continue
        media_url = urljoin(dash_url, base.text.strip())

        if height_raw and height_raw.isdigit():
            height = int(height_raw)
            width = int(width_raw) if width_raw and width_raw.isdigit() else None
            if height in TARGET_RESOLUTIONS:
                variants.setdefault(
                    height,
                    RedditVariant(height=height, width=width, url=media_url),
                )
        elif "audio" in mime or "audio" in content_type:
            audio_candidates.append(media_url)

    audio_url = audio_candidates[0] if audio_candidates else None
    return list(variants.values()), audio_url


def _variant_from_fallback(url: str) -> RedditVariant | None:
    match = re.search(r"/(?:DASH_|m2-res_)(\d+)(?:p)?\.mp4(?:\?|$)", url)
    if not match:
        return None
    height = int(match.group(1))
    if height not in TARGET_RESOLUTIONS:
        return None
    parsed = urlparse(url)
    return RedditVariant(height=height, width=None, url=url)


def _resolve_with_ytdlp(url: str) -> RedditResolvedVideo:
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "js_runtimes": {"node": {}},
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    variants_by_quality: dict[int, dict[str, Any]] = {}
    best_audio_id: str | None = None
    best_audio_score = (-1.0, -1.0)

    for item in info.get("formats") or []:
        format_id = item.get("format_id")
        if not isinstance(format_id, str) or not format_id:
            continue

        vcodec = item.get("vcodec")
        acodec = item.get("acodec")
        has_video = bool(vcodec and vcodec != "none")
        has_audio = bool(acodec and acodec != "none")

        if not has_video and has_audio:
            abr = item.get("abr")
            tbr = item.get("tbr")
            score = (
                float(abr) if isinstance(abr, (int, float)) else 0.0,
                float(tbr) if isinstance(tbr, (int, float)) else 0.0,
            )
            if score > best_audio_score:
                best_audio_score = score
                best_audio_id = format_id
            continue

        if not has_video:
            continue

        height = item.get("height")
        width = item.get("width")
        if not isinstance(height, int) or height <= 0:
            continue
        if not isinstance(width, int) or width <= 0:
            width = None

        quality = min(width, height) if width else height
        if quality not in TARGET_RESOLUTIONS:
            continue

        tbr = item.get("tbr")
        score = (
            1 if has_audio else 0,
            float(tbr) if isinstance(tbr, (int, float)) else 0.0,
            width or 0,
        )
        current = variants_by_quality.get(quality)
        if current is None or score > current["score"]:
            variants_by_quality[quality] = {
                "height": quality,
                "width": width,
                "url": item.get("url") or "",
                "format_id": format_id,
                "has_audio": has_audio,
                "score": score,
            }

    variants = tuple(
        RedditVariant(
            height=item["height"],
            width=item["width"],
            url=item["url"],
            format_id=item["format_id"],
            has_audio=item["has_audio"],
        )
        for item in sorted(
            variants_by_quality.values(),
            key=lambda item: item["height"],
            reverse=True,
        )
        if item["url"]
    )
    if not variants:
        raise ValueError("No supported Reddit video resolution at 480p or higher")

    duration = info.get("duration")
    return RedditResolvedVideo(
        title=str(info.get("title") or "Reddit video"),
        duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
        variants=variants,
        audio_url=None,
        source_url=url,
        audio_format_id=best_audio_id,
    )


class RedditVideoResolver:
    """Resolve Reddit-hosted videos into exact 1080/720/480 variants."""

    def resolve(self, url: str) -> RedditResolvedVideo:
        with _http_client() as client:
            metadata, title, duration = _extract_json_metadata(client, url)

            dash_url = metadata.get("dash_url") if metadata else None
            fallback_url = metadata.get("fallback_url") if metadata else None

            html = ""
            if not dash_url or not fallback_url:
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    html = response.text
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in {401, 403}:
                        return _resolve_with_ytdlp(url)
                    raise

            html_dash, html_variants, html_fallback = _extract_urls_from_html(html) if html else (None, [], None)
            dash_url = dash_url or html_dash
            fallback_url = fallback_url or html_fallback

            variants: dict[int, RedditVariant] = {}
            audio_url = None

            if dash_url:
                mpd_variants, mpd_audio = _parse_mpd(client, dash_url)
                for item in mpd_variants:
                    variants[item.height] = item
                audio_url = mpd_audio

            for height, media_url in html_variants:
                variants.setdefault(
                    height,
                    RedditVariant(height=height, width=None, url=media_url),
                )

            if fallback_url:
                item = _variant_from_fallback(fallback_url)
                if item:
                    variants[item.height] = item

            if title is None:
                title = urlparse(url).path.rstrip("/").split("/")[-1] or "Reddit video"

            available = tuple(
                item for item in variants.values()
                if item.height in TARGET_RESOLUTIONS
            )

            if not available:
                raise ValueError("No supported Reddit video resolution at 480p or higher")

            return RedditResolvedVideo(
                title=title,
                duration_seconds=duration,
                variants=tuple(sorted(available, key=lambda item: item.height, reverse=True)),
                audio_url=audio_url,
                source_url=url,
            )


class RedditVideoDownloadEngine:
    def __init__(self, *, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe") -> None:
        self.ffmpeg = FFmpegTools(ffmpeg_path, ffprobe_path)

    def download(
        self,
        resolved: RedditResolvedVideo,
        target_height: int,
        *,
        job_id: str,
    ) -> DownloadResult:
        self.ffmpeg.check()
        variant = resolved.variant_for(target_height)
        if variant is None:
            raise ValueError(f"Reddit resolution {target_height}p is not available")

        if resolved.source_url and variant.format_id:
            root = Path(settings.download_root)
            job_dir = root / job_id
            if job_dir.exists():
                import shutil
                shutil.rmtree(job_dir)
            job_dir.mkdir(parents=True, exist_ok=True)

            selector = variant.format_id
            if not variant.has_audio and resolved.audio_format_id:
                selector = f"{variant.format_id}+{resolved.audio_format_id}"

            options = {
                "format": selector,
                "outtmpl": str(job_dir / "%(id)s.%(ext)s"),
                "merge_output_format": "mp4",
                "ffmpeg_location": settings.ffmpeg_path,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "overwrites": True,
                "js_runtimes": {"node": {}},
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                code = ydl.download([resolved.source_url])
            if code not in (None, 0):
                raise RuntimeError(f"yt-dlp Reddit download failed with code {code}")

            candidates = [
                path for path in job_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
            ]
            if not candidates:
                raise FileNotFoundError(f"No Reddit video file was produced in {job_dir}")

            output = max(candidates, key=lambda path: path.stat().st_size)
            probe = self.ffmpeg.probe(output)
            max_size_bytes = settings.telegram_max_upload_mb * 1024 * 1024
            return DownloadResult(
                job_id=job_id,
                file_path=output,
                target_height=target_height,
                selected_format=f"reddit:{selector}",
                estimated_size=None,
                actual_size=probe.size_bytes,
                exceeds_planning_limit=probe.size_bytes > max_size_bytes,
                probe=probe,
            )
        root = Path(settings.download_root)
        job_dir = root / job_id
        if job_dir.exists():
            import shutil
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)

        output = job_dir / f"reddit_{target_height}p.mp4"

        headers = (
            f"User-Agent: {USER_AGENT}\r\n"
            "Referer: https://www.reddit.com/\r\n"
            "Origin: https://www.reddit.com\r\n"
        )

        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-loglevel", "error",
            "-headers", headers,
            "-i", variant.url,
        ]

        if resolved.audio_url:
            cmd += [
                "-headers", headers,
                "-i", resolved.audio_url,
                "-map", "0:v:0",
                "-map", "1:a:0?",
            ]

        cmd += [
            "-c", "copy",
            "-movflags", "+faststart",
            str(output),
        ]

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or "FFmpeg failed to download Reddit video"
            )

        probe = self.ffmpeg.probe(output)
        max_size_bytes = settings.telegram_max_upload_mb * 1024 * 1024

        return DownloadResult(
            job_id=job_id,
            file_path=output,
            target_height=target_height,
            selected_format=f"reddit:{target_height}p",
            estimated_size=None,
            actual_size=probe.size_bytes,
            exceeds_planning_limit=probe.size_bytes > max_size_bytes,
            probe=probe,
        )
