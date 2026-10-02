from __future__ import annotations

import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import settings
from .download_engine import DownloadResult
from .media_tools import FFmpegTools
from .video_analyzer import TARGET_RESOLUTIONS

INSTANCE_LIST_URL = "https://raw.githubusercontent.com/wiki/TeamPiped/Piped/Instances.md"

# These instances were independently observed serving the /streams endpoint
# recently; keep them ahead of the larger public list so a broken instance
# cannot consume the entire metadata probe window.
PRIORITY_PIPED_INSTANCES = (
    "https://pipedapi.ducks.party",
    "https://api.piped.private.coffee",
)

DEFAULT_PIPED_INSTANCES = (
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.leptons.xyz",
    "https://pipedapi.nosebs.ru",
    "https://pipedapi-libre.kavin.rocks",
    "https://piped-api.privacy.com.de",
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
    "https://pipedapi.drgns.space",
    "https://pipedapi.owo.si",
    "https://pipedapi.ducks.party",
    "https://api.piped.private.coffee",
    "https://pipedapi.darkness.services",
    "https://pipedapi.orangenet.cc",
)


@dataclass(frozen=True)
class PipedInfo:
    title: str
    duration_seconds: float | None
    available_heights: tuple[int, ...]
    size_by_height: dict[int, int]
    instance_url: str


def youtube_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")

    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        query_match = re.search(r"(?:^|&)v=([A-Za-z0-9_-]{11})(?:&|$)", parsed.query)
        if query_match:
            video_id = query_match.group(1)
        else:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
                video_id = parts[1]

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Invalid YouTube video URL")
    return video_id


def _quality_height(item: dict) -> int | None:
    for value in (item.get("quality"), item.get("height")):
        if isinstance(value, int) and value in TARGET_RESOLUTIONS:
            return value
        if isinstance(value, str):
            match = re.fullmatch(r"(\d+)p", value.strip().lower())
            if match:
                height = int(match.group(1))
                if height in TARGET_RESOLUTIONS:
                    return height
    return None


def _stream_size(item: dict) -> int | None:
    for key in ("contentLength", "content_length", "file_size", "size"):
        value = item.get(key)
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


@lru_cache(maxsize=1)
def _dynamic_instances() -> tuple[str, ...]:
    try:
        response = httpx.get(INSTANCE_LIST_URL, timeout=5.0)
        response.raise_for_status()
        urls = re.findall(r"https://[A-Za-z0-9.-]+", response.text)
        found = []
        for value in urls:
            host = urlparse(value).hostname or ""
            normalized = value.rstrip("/")
            if "piped" in host and normalized not in found:
                found.append(normalized)
        if found:
            return tuple(found)
    except Exception:
        pass
    return DEFAULT_PIPED_INSTANCES


def _instance_candidates() -> tuple[str, ...]:
    values = []
    for value in (*PRIORITY_PIPED_INSTANCES, *_dynamic_instances(), *DEFAULT_PIPED_INSTANCES):
        normalized = value.rstrip("/")
        if normalized and normalized not in values:
            values.append(normalized)
    return tuple(values)


MAX_PIPED_METADATA_INSTANCES = 8
PIPED_METADATA_TIMEOUT_SECONDS = 8.0


class PipedYouTubeClient:
    """Resolve YouTube via Piped's backend/proxy instead of Blitz's YouTube IP."""

    def __init__(self, *, ffmpeg_path: str | None = None, ffprobe_path: str | None = None) -> None:
        self.ffmpeg = FFmpegTools(ffmpeg_path, ffprobe_path)

    @staticmethod
    def _video_candidates(payload: dict) -> list[dict]:
        return [
            item for item in payload.get("videoStreams", [])
            if isinstance(item, dict)
            and isinstance(item.get("url"), str)
            and item.get("url")
            and _quality_height(item) in TARGET_RESOLUTIONS
        ]

    @staticmethod
    def _audio_candidates(payload: dict) -> list[dict]:
        return [
            item for item in payload.get("audioStreams", [])
            if isinstance(item, dict)
            and isinstance(item.get("url"), str)
            and item.get("url")
        ]

    @staticmethod
    def _fetch_payload(instance: str, video_id: str) -> tuple[str, dict]:
        response = httpx.get(
            f"{instance}/streams/{video_id}",
            timeout=PIPED_METADATA_TIMEOUT_SECONDS,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("invalid JSON response")
        videos = PipedYouTubeClient._video_candidates(payload)
        if not videos:
            raise RuntimeError("no 480p+ streams")
        return instance, payload

    def _get_payload(self, video_id: str, preferred_instance: str | None = None) -> tuple[str, dict]:
        candidates = []
        if preferred_instance:
            candidates.append(preferred_instance.rstrip("/"))
        candidates.extend(
            item for item in _instance_candidates()
            if item.rstrip("/") not in candidates
        )
        candidates = candidates[:MAX_PIPED_METADATA_INSTANCES]

        errors = []
        with ThreadPoolExecutor(max_workers=len(candidates) or 1) as executor:
            futures = {
                executor.submit(self._fetch_payload, instance, video_id): instance
                for instance in candidates
            }
            for future in as_completed(futures):
                instance = futures[future]
                try:
                    return future.result()
                except Exception as exc:
                    errors.append(f"{instance}: {type(exc).__name__}: {exc}")

        raise RuntimeError(
            "No responsive Piped instance returned a usable 480p+ stream within the timeout: "
            + " | ".join(errors)
        )

    def inspect(self, url: str) -> PipedInfo:
        video_id = youtube_video_id(url)
        instance, payload = self._get_payload(video_id)
        videos = self._video_candidates(payload)
        audios = self._audio_candidates(payload)

        heights = tuple(
            height for height in TARGET_RESOLUTIONS
            if any(_quality_height(item) == height for item in videos)
        )

        best_audio_size = max(
            (_stream_size(item) or 0 for item in audios),
            default=0,
        )
        sizes = {}
        for height in heights:
            candidates = [item for item in videos if _quality_height(item) == height]
            progressive_sizes = [
                _stream_size(item) or 0
                for item in candidates
                if item.get("videoOnly") is False
            ]
            if progressive_sizes:
                sizes[height] = max(progressive_sizes)
            elif best_audio_size:
                video_sizes = [_stream_size(item) for item in candidates]
                video_sizes = [size for size in video_sizes if size is not None]
                if video_sizes:
                    sizes[height] = max(video_sizes) + best_audio_size

        duration = payload.get("duration")
        return PipedInfo(
            title=str(payload.get("title") or "YouTube video"),
            duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
            available_heights=heights,
            size_by_height=sizes,
            instance_url=instance,
        )

    def download(
        self,
        url: str,
        target_height: int,
        *,
        job_id: str,
        estimated_size: int | None = None,
    ) -> DownloadResult:
        self.ffmpeg.check()
        video_id = youtube_video_id(url)

        root = Path(settings.download_root)
        job_dir = root / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)

        info = self.inspect(url)
        instances = (info.instance_url,) + tuple(
            item for item in _instance_candidates()
            if item != info.instance_url
        )
        instances = instances[:MAX_PIPED_METADATA_INSTANCES]
        last_error: Exception | None = None

        for instance in instances:
            try:
                _, payload = self._get_payload(video_id, preferred_instance=instance)
                videos = [
                    item for item in self._video_candidates(payload)
                    if _quality_height(item) == target_height
                ]
                audios = self._audio_candidates(payload)
                if not videos:
                    continue

                progressive = [item for item in videos if item.get("videoOnly") is False]
                output = job_dir / f"{video_id}_{target_height}p.mp4"

                if progressive:
                    selected = max(
                        progressive,
                        key=lambda item: (
                            _stream_size(item) or 0,
                            item.get("width") or 0,
                        ),
                    )
                    self._download_url(selected["url"], output)
                else:
                    selected = max(
                        videos,
                        key=lambda item: (
                            item.get("width") or 0,
                            _stream_size(item) or 0,
                        ),
                    )
                    if not audios:
                        raise RuntimeError("No Piped audio stream returned")
                    audio = max(
                        audios,
                        key=lambda item: (
                            _stream_size(item) or 0,
                            item.get("bitrate") or 0,
                        ),
                    )
                    self._merge_urls(selected["url"], audio["url"], output)

                probe = self.ffmpeg.probe(output)
                return DownloadResult(
                    job_id=job_id,
                    file_path=output,
                    target_height=target_height,
                    selected_format=f"piped:{target_height}p",
                    estimated_size=estimated_size,
                    actual_size=probe.size_bytes,
                    exceeds_planning_limit=probe.size_bytes
                    > settings.telegram_max_upload_mb * 1024 * 1024,
                    probe=probe,
                )
            except Exception as exc:
                last_error = exc
                shutil.rmtree(job_dir, ignore_errors=True)
                job_dir.mkdir(parents=True, exist_ok=True)

        raise RuntimeError(
            f"All Piped media downloads failed for {target_height}p: {last_error}"
        )

    @staticmethod
    def _download_url(url: str, output: Path) -> None:
        with httpx.stream("GET", url, follow_redirects=True, timeout=None) as response:
            response.raise_for_status()
            with output.open("wb") as stream:
                for chunk in response.iter_bytes(1024 * 1024):
                    stream.write(chunk)

    @staticmethod
    def _merge_urls(video_url: str, audio_url: str, output: Path) -> None:
        completed = subprocess.run(
            [
                settings.ffmpeg_path,
                "-y",
                "-loglevel",
                "error",
                "-i",
                video_url,
                "-i",
                audio_url,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip() or "FFmpeg failed to merge Piped streams"
            )
