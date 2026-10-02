from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import re

import httpx

from .config import settings
from .download_engine import DownloadResult
from .media_tools import FFmpegTools
from .video_analyzer import TARGET_RESOLUTIONS

ALLDL_API_URL = "https://ahm7xmakki.com/api/alldl"


class AllDLUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class AllDLQuality:
    height: int
    url: str


@dataclass(frozen=True)
class AllDLMedia:
    title: str
    platform: str
    video_url: str
    qualities: tuple[AllDLQuality, ...]

    @property
    def available_heights(self) -> tuple[int, ...]:
        return tuple(
            height
            for height in TARGET_RESOLUTIONS
            if any(item.height == height for item in self.qualities)
        )

    def url_for_height(self, height: int) -> str:
        for item in self.qualities:
            if item.height == height:
                return item.url
        if self.qualities:
            raise AllDLUnavailableError(
                f"AHM7 AllDL did not return {height}p for this media"
            )
        return self.video_url


class AllDLResolver:
    """Resolve public video URLs through the AHM7 AllDL API."""

    def __init__(
        self,
        *,
        api_url: str = ALLDL_API_URL,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds

    def resolve(self, url: str) -> AllDLMedia:
        try:
            response = httpx.get(
                self.api_url,
                params={"url": url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AllDLUnavailableError(
                f"AHM7 AllDL request failed: {type(exc).__name__}"
            ) from exc

        if not isinstance(payload, dict) or payload.get("success") is not True:
            message = (
                payload.get("message")
                if isinstance(payload, dict)
                else None
            )
            raise AllDLUnavailableError(
                f"AHM7 AllDL rejected the URL: {message or 'unknown error'}"
            )

        media_info = payload.get("mediaInfo")
        if not isinstance(media_info, dict):
            raise AllDLUnavailableError("AHM7 AllDL returned no mediaInfo")

        video_url = str(media_info.get("videoUrl") or "").strip()
        if not video_url:
            raise AllDLUnavailableError("AHM7 AllDL returned no videoUrl")

        qualities: list[AllDLQuality] = []
        raw_qualities = media_info.get("qualities") or []
        if isinstance(raw_qualities, list):
            for raw in raw_qualities:
                if not isinstance(raw, dict):
                    continue
                quality_url = str(raw.get("url") or "").strip()
                if not quality_url:
                    continue
                raw_height = raw.get("height") or raw.get("quality")
                match = re.search(r"(?:^|\D)(1080|720|480)(?:p)?(?:\D|$)", str(raw_height))
                if not match:
                    continue
                qualities.append(
                    AllDLQuality(
                        height=int(match.group(1)),
                        url=quality_url,
                    )
                )

        unique: dict[int, AllDLQuality] = {}
        for item in qualities:
            unique[item.height] = item

        return AllDLMedia(
            title=str(media_info.get("title") or "video"),
            platform=str(media_info.get("platform") or "unknown"),
            video_url=video_url,
            qualities=tuple(
                unique[height]
                for height in sorted(unique, reverse=True)
            ),
        )


def _safe_name(value: str) -> str:
    value = re.sub(r"[^\w\-. ]+", "", value, flags=re.UNICODE).strip()
    return value[:80] or "video"


class AllDLVideoDownloadEngine:
    """Download the direct media URL returned by AHM7 and verify the real file."""

    def __init__(
        self,
        *,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        self.ffmpeg = FFmpegTools(ffmpeg_path, ffprobe_path)
        self.timeout = httpx.Timeout(timeout_seconds)

    def download(
        self,
        media: AllDLMedia,
        target_height: int,
        *,
        job_id: str,
    ) -> DownloadResult:
        self.ffmpeg.check()

        root = Path(settings.download_root)
        job_dir = root / job_id
        if job_dir.exists():
            import shutil
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)

        direct_url = media.url_for_height(target_height)
        suffix = Path(urlparse(direct_url).path).suffix.lower()
        if suffix not in {".mp4", ".mkv", ".webm", ".mov", ".avi"}:
            suffix = ".mp4"

        output = job_dir / f"{_safe_name(media.title)}-{target_height}p{suffix}"

        try:
            with httpx.stream(
                "GET",
                direct_url,
                timeout=self.timeout,
                follow_redirects=True,
            ) as response:
                response.raise_for_status()
                with output.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if chunk:
                            handle.write(chunk)
        except (httpx.HTTPError, OSError) as exc:
            raise AllDLUnavailableError(
                f"AHM7 media download failed: {type(exc).__name__}"
            ) from exc

        if not output.exists() or output.stat().st_size <= 0:
            raise AllDLUnavailableError("AHM7 returned an empty media file")

        probe = self.ffmpeg.probe(output)
        return DownloadResult(
            job_id=job_id,
            file_path=output,
            target_height=target_height,
            selected_format=f"alldl:{target_height}p",
            estimated_size=None,
            actual_size=probe.size_bytes,
            exceeds_planning_limit=(
                probe.size_bytes
                > 2000 * 1024 * 1024
            ),
            probe=probe,
        )
