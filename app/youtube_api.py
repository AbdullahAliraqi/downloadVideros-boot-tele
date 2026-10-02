from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import settings
from .media_tools import FFmpegTools, MediaProbeResult
from .video_analyzer import TARGET_RESOLUTIONS


@dataclass(frozen=True)
class TunelioInfo:
    title: str
    duration_seconds: float | None
    available_heights: tuple[int, ...]
    size_by_height: dict[int, int]


def _quality_height(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value in TARGET_RESOLUTIONS else None
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\\d+)p", value.strip().lower())
    if not match:
        return None
    height = int(match.group(1))
    return height if height in TARGET_RESOLUTIONS else None


def _size_bytes(item: dict[str, Any]) -> int | None:
    for key in ("size_bytes", "filesize", "file_size_bytes", "size"):
        value = item.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value >= 0:
            return int(value)
        if isinstance(value, str):
            digits = re.sub(r"[^0-9]", "", value)
            if digits:
                return int(digits)
    return None


class TunelioYouTubeClient:
    """Managed YouTube provider used when direct yt-dlp extraction is blocked."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.tunelio_api_key).strip()
        self.base_url = (base_url if base_url is not None else settings.tunelio_api_base_url).rstrip("/")
        self.ffmpeg = FFmpegTools(ffmpeg_path, ffprobe_path)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("TUNELIO_API_KEY is not configured")
        return {"Authorization": f"Bearer {self.api_key}"}

    def inspect(self, url: str) -> TunelioInfo:
        with httpx.Client(timeout=45.0) as client:
            response = client.get(
                f"{self.base_url}/info",
                params={"url": url},
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, dict):
            raise RuntimeError("Tunelio /info returned an invalid response")

        formats = payload.get("formats")
        if not isinstance(formats, list):
            raise RuntimeError("Tunelio /info did not return formats")

        heights: set[int] = set()
        sizes: dict[int, int] = {}
        for item in formats:
            if not isinstance(item, dict):
                continue
            height = _quality_height(
                item.get("quality")
                or item.get("quality_label")
                or item.get("height")
            )
            if height is None:
                continue
            heights.add(height)
            size = _size_bytes(item)
            if size is not None:
                sizes[height] = size

        duration = payload.get("duration_seconds")
        duration_seconds = float(duration) if isinstance(duration, (int, float)) else None
        title = str(payload.get("title") or "YouTube video")
        return TunelioInfo(
            title=title,
            duration_seconds=duration_seconds,
            available_heights=tuple(
                height for height in TARGET_RESOLUTIONS if height in heights
            ),
            size_by_height=sizes,
        )

    def download(
        self,
        url: str,
        target_height: int,
        *,
        job_id: str,
        estimated_size: int | None = None,
    ):
        self.ffmpeg.check()
        root = Path(settings.download_root)
        job_dir = root / job_id
        if job_dir.exists():
            import shutil
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)

        quality = f"{target_height}p"
        with httpx.Client(timeout=None, follow_redirects=True) as client:
            response = client.get(
                f"{self.base_url}/create",
                params={"url": url, "quality": quality},
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise RuntimeError(f"Tunelio /create failed: {payload!r}")

            download_url = payload.get("url")
            if not isinstance(download_url, str) or not download_url:
                raise RuntimeError("Tunelio /create did not return a download URL")

            filename = payload.get("filename")
            if not isinstance(filename, str) or not filename:
                filename = f"youtube_{target_height}p.mp4"
            safe_name = Path(filename).name or f"youtube_{target_height}p.mp4"
            output = job_dir / safe_name

            with client.stream("GET", download_url) as media:
                media.raise_for_status()
                with output.open("wb") as stream:
                    for chunk in media.iter_bytes(1024 * 1024):
                        stream.write(chunk)

        probe = self.ffmpeg.probe(output)
        from .download_engine import DownloadResult

        return DownloadResult(
            job_id=job_id,
            file_path=output,
            target_height=target_height,
            selected_format=f"tunelio:{quality}",
            estimated_size=estimated_size,
            actual_size=probe.size_bytes,
            exceeds_planning_limit=probe.size_bytes
            > settings.telegram_max_upload_mb * 1024 * 1024,
            probe=probe,
        )
