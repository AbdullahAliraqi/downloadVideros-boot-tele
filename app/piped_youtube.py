from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from .config import settings
from .download_engine import DownloadResult
from .media_tools import FFmpegTools
from .video_analyzer import TARGET_RESOLUTIONS

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/154.0 Safari/537.36"
)

# Public Piped instances are not an implicit production dependency.
# Configure PIPED_API_URLS only with an instance that has been verified
# from the actual deployment environment.
DEFAULT_PIPED_API_URLS: tuple[str, ...] = ()


class PipedUnavailableError(RuntimeError):
    """Raised when no configured Piped instance can resolve a YouTube video."""


@dataclass(frozen=True)
class PipedVideoStream:
    height: int
    width: int | None
    url: str
    mime_type: str
    bitrate: int
    video_only: bool


@dataclass(frozen=True)
class PipedAudioStream:
    url: str
    mime_type: str
    bitrate: int


@dataclass(frozen=True)
class PipedResolvedVideo:
    video_id: str
    title: str
    duration_seconds: float | None
    video_streams: tuple[PipedVideoStream, ...]
    audio_streams: tuple[PipedAudioStream, ...]
    api_base_url: str

    @property
    def available_heights(self) -> tuple[int, ...]:
        return tuple(
            target
            for target in TARGET_RESOLUTIONS
            if any(
                item.height == target and item.mime_type == "video/mp4"
                for item in self.video_streams
            )
        )

    def video_for(self, height: int) -> PipedVideoStream | None:
        candidates = [
            item
            for item in self.video_streams
            if item.height == height and item.mime_type == "video/mp4"
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                0 if item.video_only else 1,
                item.width or 0,
                item.bitrate,
            ),
        )

    def best_audio(self) -> PipedAudioStream | None:
        candidates = [
            item for item in self.audio_streams
            if item.mime_type == "audio/mp4"
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.bitrate)


def _parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def extract_youtube_video_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]

    if host == "youtu.be":
        value = parsed.path.strip("/").split("/", 1)[0]
        return value or None

    if host == "youtube.com" or host.endswith(".youtube.com"):
        query_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_id:
            return query_id

        match = re.match(
            r"^/(?:shorts|embed|live)/([A-Za-z0-9_-]{6,})",
            parsed.path,
        )
        if match:
            return match.group(1)

    return None


def _configured_api_urls() -> tuple[str, ...]:
    if settings.piped_api_urls:
        return settings.piped_api_urls
    return DEFAULT_PIPED_API_URLS


class PipedYoutubeResolver:
    """Resolve YouTube streams through documented public Piped API instances."""

    def __init__(
        self,
        *,
        api_urls: tuple[str, ...] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_urls = tuple(
            item.rstrip("/") for item in (api_urls or _configured_api_urls()) if item
        )
        self.timeout = timeout

    def resolve(self, url: str) -> PipedResolvedVideo:
        video_id = extract_youtube_video_id(url)
        if not video_id:
            raise PipedUnavailableError("Could not extract a YouTube video ID")

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        last_error: Exception | None = None
        errors: list[str] = []

        with httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=self.timeout,
        ) as client:
            for base_url in self.api_urls:
                try:
                    response = client.get(f"{base_url}/streams/{video_id}")
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("Piped returned a non-object response")

                    raw_video_streams = payload.get("videoStreams") or []
                    raw_audio_streams = payload.get("audioStreams") or []
                    if not isinstance(raw_video_streams, list):
                        raise ValueError("Piped returned invalid videoStreams")
                    if not isinstance(raw_audio_streams, list):
                        raise ValueError("Piped returned invalid audioStreams")

                    video_streams = tuple(
                        PipedVideoStream(
                            height=_parse_int(item.get("height")),
                            width=_parse_int(item.get("width")) or None,
                            url=str(item.get("url") or ""),
                            mime_type=str(item.get("mimeType") or "").lower(),
                            bitrate=_parse_int(item.get("bitrate")),
                            video_only=bool(item.get("videoOnly")),
                        )
                        for item in raw_video_streams
                        if isinstance(item, dict)
                        and item.get("url")
                        and _parse_int(item.get("height")) in TARGET_RESOLUTIONS
                    )
                    audio_streams = tuple(
                        PipedAudioStream(
                            url=str(item.get("url") or ""),
                            mime_type=str(item.get("mimeType") or "").lower(),
                            bitrate=_parse_int(item.get("bitrate")),
                        )
                        for item in raw_audio_streams
                        if isinstance(item, dict) and item.get("url")
                    )

                    resolved = PipedResolvedVideo(
                        video_id=video_id,
                        title=str(payload.get("title") or video_id),
                        duration_seconds=(
                            float(payload["duration"])
                            if isinstance(payload.get("duration"), (int, float))
                            else None
                        ),
                        video_streams=video_streams,
                        audio_streams=audio_streams,
                        api_base_url=base_url,
                    )
                    if not resolved.available_heights:
                        raise ValueError(
                            "Piped returned no supported 1080p/720p/480p MP4 stream"
                        )
                    return resolved
                except Exception as exc:
                    last_error = exc
                    errors.append(f"{base_url}: {type(exc).__name__}: {exc}")

        detail = "; ".join(errors) if errors else "no Piped API instances configured"
        raise PipedUnavailableError(
            f"All configured Piped instances failed for YouTube video {video_id}: {detail}"
        ) from last_error


class PipedYoutubeDownloadEngine:
    def __init__(
        self,
        *,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
    ) -> None:
        self.ffmpeg = FFmpegTools(ffmpeg_path, ffprobe_path)

    @staticmethod
    def _job_dir(job_id: str) -> Path:
        return Path(settings.download_root) / job_id

    @staticmethod
    def _reset_job_dir(job_id: str) -> Path:
        job_dir = PipedYoutubeDownloadEngine._job_dir(job_id)
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    @staticmethod
    def _download_stream(
        client: httpx.Client,
        url: str,
        destination: Path,
    ) -> None:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with destination.open("wb") as output:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)

    def download(
        self,
        resolved: PipedResolvedVideo,
        target_height: int,
        *,
        job_id: str,
    ) -> DownloadResult:
        self.ffmpeg.check()
        video = resolved.video_for(target_height)
        if video is None:
            raise ValueError(f"Piped YouTube resolution {target_height}p is not available")

        job_dir = self._reset_job_dir(job_id)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        }
        timeout = httpx.Timeout(connect=30.0, read=None, write=None, pool=30.0)

        output = job_dir / f"{resolved.video_id}_{target_height}p.mp4"

        with httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            if video.video_only:
                audio = resolved.best_audio()
                if audio is None:
                    raise PipedUnavailableError(
                        "Piped did not provide an MP4 audio stream for this video"
                    )

                video_file = job_dir / "video.mp4"
                audio_file = job_dir / "audio.m4a"
                self._download_stream(client, video.url, video_file)
                self._download_stream(client, audio.url, audio_file)

                completed = subprocess.run(
                    [
                        settings.ffmpeg_path,
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        str(video_file),
                        "-i",
                        str(audio_file),
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
                        completed.stderr.strip() or "FFmpeg failed to mux Piped streams"
                    )
            else:
                self._download_stream(client, video.url, output)

        if not output.is_file() or output.stat().st_size <= 0:
            raise FileNotFoundError("Piped download produced no video file")

        probe = self.ffmpeg.probe(output)
        max_size_bytes = settings.telegram_max_upload_mb * 1024 * 1024
        return DownloadResult(
            job_id=job_id,
            file_path=output,
            target_height=target_height,
            selected_format=f"piped:{target_height}p",
            estimated_size=None,
            actual_size=probe.size_bytes,
            exceeds_planning_limit=probe.size_bytes > max_size_bytes,
            probe=probe,
        )
