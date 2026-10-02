from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from .config import settings
from .download_engine import DownloadResult
from .media_tools import FFmpegTools
from .video_analyzer import TARGET_RESOLUTIONS


class YouTubeCompanionError(RuntimeError):
    """Base error for the internal YouTube Companion gateway."""


class YouTubeCompanionConfigurationError(YouTubeCompanionError):
    """The bot/Companion configuration is invalid."""


class YouTubeCompanionTransientError(YouTubeCompanionError):
    """The Companion service is temporarily unavailable."""


class YouTubeCompanionBlockedError(YouTubeCompanionError):
    """YouTube rejected the Companion player request."""


@dataclass(frozen=True)
class YouTubeStream:
    itag: int
    width: int | None
    height: int | None
    mime_type: str
    bitrate: int
    has_video: bool
    has_audio: bool
    content_length: int | None

    @property
    def quality_level(self) -> int | None:
        if not self.has_video:
            return None
        if self.width is not None and self.height is not None:
            return min(self.width, self.height)
        return self.height


@dataclass(frozen=True)
class YouTubeResolvedVideo:
    video_id: str
    title: str
    duration_seconds: float | None
    streams: tuple[YouTubeStream, ...]

    def _video_streams(self) -> tuple[YouTubeStream, ...]:
        return tuple(
            item
            for item in self.streams
            if item.has_video and item.mime_type == "video/mp4"
        )

    def _audio_streams(self) -> tuple[YouTubeStream, ...]:
        return tuple(
            item
            for item in self.streams
            if item.has_audio and not item.has_video and item.mime_type == "audio/mp4"
        )

    @property
    def available_heights(self) -> tuple[int, ...]:
        audio_available = bool(self._audio_streams())
        return tuple(
            target
            for target in TARGET_RESOLUTIONS
            if any(
                stream.quality_level == target
                and (stream.has_audio or audio_available)
                for stream in self._video_streams()
            )
        )

    def best_video(self, height: int) -> YouTubeStream | None:
        candidates = [
            item for item in self._video_streams()
            if item.quality_level == height
            and (item.has_audio or self._audio_streams())
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item.bitrate,
                1 if item.has_audio else 0,
                item.width or 0,
            ),
        )

    def best_audio(self) -> YouTubeStream | None:
        candidates = list(self._audio_streams())
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.bitrate, item.content_length or 0))


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
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1] or None
    return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _stream_from_raw(raw: object) -> YouTubeStream | None:
    if not isinstance(raw, dict):
        return None

    itag = _int_or_none(raw.get("itag"))
    if itag is None:
        return None

    mime_type = str(raw.get("mimeType") or "").split(";", 1)[0].lower()
    has_video = mime_type.startswith("video/")
    has_audio = mime_type.startswith("audio/") or bool(raw.get("audioQuality"))
    if not has_video and not has_audio:
        return None

    return YouTubeStream(
        itag=itag,
        width=_int_or_none(raw.get("width")),
        height=_int_or_none(raw.get("height")),
        mime_type=mime_type,
        bitrate=_int_or_none(raw.get("bitrate")) or 0,
        has_video=has_video,
        has_audio=has_audio,
        content_length=_int_or_none(raw.get("contentLength")),
    )


class YouTubeCompanionGateway:
    """YouTube acquisition gateway backed by the official Invidious Companion project."""

    _NOT_READY_MARKERS = (
        "not ready",
        "initializing",
        "token generator",
        "po token",
    )
    _BLOCKED_MARKERS = (
        "sign in to confirm",
        "not a bot",
        "captcha",
        "bot check",
        "login_required",
    )

    def __init__(
        self,
        *,
        base_url: str | None = None,
        secret_key: str | None = None,
        timeout_seconds: float = 45.0,
        readiness_retries: int = 3,
    ) -> None:
        self.base_url = (base_url or settings.youtube_companion_base_url).rstrip("/")
        self.secret_key = secret_key or settings.youtube_companion_secret_key
        self.timeout_seconds = timeout_seconds
        self.readiness_retries = readiness_retries

    def _validate_config(self) -> None:
        if not self.base_url:
            raise YouTubeCompanionConfigurationError(
                "YOUTUBE_COMPANION_BASE_URL is not configured"
            )
        if len(self.secret_key) != 16:
            raise YouTubeCompanionConfigurationError(
                "YOUTUBE_COMPANION_SECRET_KEY must contain exactly 16 characters"
            )

    def _headers(self) -> dict[str, str]:
        self._validate_config()
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Accept": "application/json",
        }

    @staticmethod
    def _playability_error(payload: dict[str, object]) -> tuple[str, str]:
        status_obj = payload.get("playabilityStatus")
        if not isinstance(status_obj, dict):
            return "", ""
        status = str(status_obj.get("status") or "")
        reason = str(status_obj.get("reason") or "")
        error_screen = status_obj.get("errorScreen")
        if isinstance(error_screen, dict):
            renderer = error_screen.get("playerErrorMessageRenderer")
            if isinstance(renderer, dict):
                reason_obj = renderer.get("reason")
                if isinstance(reason_obj, dict):
                    simple_text = reason_obj.get("simpleText")
                    if simple_text and not reason:
                        reason = str(simple_text)
        return status, reason

    def _request_player(self, video_id: str) -> dict[str, object]:
        headers = self._headers()
        last_error: Exception | None = None

        with httpx.Client(
            headers=headers,
            timeout=httpx.Timeout(
                connect=15.0,
                read=self.timeout_seconds,
                write=15.0,
                pool=15.0,
            ),
            follow_redirects=True,
        ) as client:
            for attempt in range(self.readiness_retries):
                try:
                    response = client.post(
                        f"{self.base_url}/youtubei/v1/player",
                        json={"videoId": video_id},
                    )
                except httpx.RequestError as exc:
                    last_error = exc
                    if attempt + 1 < self.readiness_retries:
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise YouTubeCompanionTransientError(
                        f"Companion player request failed: {exc}"
                    ) from exc

                if response.status_code in {401, 403}:
                    raise YouTubeCompanionConfigurationError(
                        f"Companion rejected the authentication key (HTTP {response.status_code})"
                    )

                if response.status_code >= 500:
                    last_error = RuntimeError(
                        f"Companion returned HTTP {response.status_code}"
                    )
                    if attempt + 1 < self.readiness_retries:
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise YouTubeCompanionTransientError(str(last_error))

                try:
                    response.raise_for_status()
                    payload = response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    raise YouTubeCompanionError(
                        f"Invalid response from YouTube Companion: {exc}"
                    ) from exc

                if not isinstance(payload, dict):
                    raise YouTubeCompanionError("YouTube Companion returned invalid player JSON")

                status, reason = self._playability_error(payload)
                if status and status != "OK":
                    detail = f"{status}: {reason or 'no reason returned'}"
                    lowered = detail.lower()
                    if any(marker in lowered for marker in self._NOT_READY_MARKERS):
                        last_error = YouTubeCompanionTransientError(detail)
                        if attempt + 1 < self.readiness_retries:
                            time.sleep(2 * (attempt + 1))
                            continue
                        raise last_error
                    if any(marker in lowered for marker in self._BLOCKED_MARKERS):
                        raise YouTubeCompanionBlockedError(detail)
                    raise YouTubeCompanionError(detail)

                return payload

        raise YouTubeCompanionTransientError(
            f"Companion player request did not succeed: {last_error}"
        )

    def resolve(self, url: str) -> YouTubeResolvedVideo:
        video_id = extract_youtube_video_id(url)
        if not video_id:
            raise YouTubeCompanionError("Could not extract a YouTube video ID")

        payload = self._request_player(video_id)
        streaming = payload.get("streamingData")
        if not isinstance(streaming, dict):
            raise YouTubeCompanionError(
                f"YouTube Companion returned no streamingData for {video_id}"
            )

        raw_formats = []
        for key in ("formats", "adaptiveFormats"):
            value = streaming.get(key) or []
            if isinstance(value, list):
                raw_formats.extend(value)

        streams = tuple(
            parsed
            for raw in raw_formats
            if (parsed := _stream_from_raw(raw)) is not None
        )

        title = video_id
        duration: float | None = None
        details = payload.get("videoDetails")
        if isinstance(details, dict):
            if details.get("title"):
                title = str(details["title"])
            raw_duration = details.get("lengthSeconds")
            try:
                duration = float(raw_duration) if raw_duration is not None else None
            except (TypeError, ValueError):
                duration = None

        resolved = YouTubeResolvedVideo(
            video_id=video_id,
            title=title,
            duration_seconds=duration,
            streams=streams,
        )
        if not resolved.available_heights:
            raise YouTubeCompanionError(
                f"YouTube Companion returned no complete MP4 resolution at or above 480p for {video_id}"
            )
        return resolved

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(
                connect=30.0,
                read=None,
                write=None,
                pool=30.0,
            ),
            follow_redirects=True,
        )

    def _download_itag(
        self,
        client: httpx.Client,
        *,
        video_id: str,
        itag: int,
        title: str,
        destination: Path,
    ) -> None:
        params = {
            "id": video_id,
            "itag": str(itag),
            "local": "true",
            "title": title,
        }
        with client.stream(
            "GET",
            f"{self.base_url}/latest_version",
            params=params,
        ) as response:
            if response.status_code in {401, 403}:
                raise YouTubeCompanionConfigurationError(
                    f"Companion latest_version rejected the request (HTTP {response.status_code})"
                )
            if response.status_code >= 500:
                raise YouTubeCompanionTransientError(
                    f"Companion latest_version returned HTTP {response.status_code}"
                )
            response.raise_for_status()

            with destination.open("wb") as output:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)

    @staticmethod
    def _reset_job_dir(job_id: str) -> Path:
        job_dir = Path(settings.download_root) / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def download(
        self,
        resolved: YouTubeResolvedVideo,
        target_height: int,
        *,
        job_id: str,
    ) -> DownloadResult:
        self._validate_config()
        video = resolved.best_video(target_height)
        if video is None:
            raise YouTubeCompanionError(
                f"YouTube Companion resolution {target_height}p is not available"
            )

        ffmpeg = FFmpegTools()
        ffmpeg.check()
        job_dir = self._reset_job_dir(job_id)

        output = job_dir / f"{resolved.video_id}_{target_height}p.mp4"
        title = resolved.title or resolved.video_id

        try:
            with self._client() as client:
                if video.has_audio:
                    self._download_itag(
                        client,
                        video_id=resolved.video_id,
                        itag=video.itag,
                        title=title,
                        destination=output,
                    )
                    selected_format = f"companion:{video.itag}"
                else:
                    audio = resolved.best_audio()
                    if audio is None:
                        raise YouTubeCompanionError(
                            f"No MP4 audio stream is available for {resolved.video_id}"
                        )

                    video_file = job_dir / "video.mp4"
                    audio_file = job_dir / "audio.m4a"
                    self._download_itag(
                        client,
                        video_id=resolved.video_id,
                        itag=video.itag,
                        title=title,
                        destination=video_file,
                    )
                    self._download_itag(
                        client,
                        video_id=resolved.video_id,
                        itag=audio.itag,
                        title=title,
                        destination=audio_file,
                    )

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
                            "-c:v",
                            "copy",
                            "-c:a",
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
                        raise YouTubeCompanionError(
                            completed.stderr.strip()
                            or "FFmpeg failed to merge Companion video and audio streams"
                        )
                    selected_format = f"companion:{video.itag}+{audio.itag}"

            if not output.is_file() or output.stat().st_size <= 0:
                raise YouTubeCompanionError("YouTube Companion produced no video file")

            probe = ffmpeg.probe(output)
            actual_quality = None
            if probe.width is not None and probe.height is not None:
                actual_quality = min(probe.width, probe.height)
            elif probe.height is not None:
                actual_quality = probe.height
            if actual_quality is not None and actual_quality != target_height:
                raise YouTubeCompanionError(
                    f"Companion returned {actual_quality}p media while {target_height}p was requested"
                )

            max_size_bytes = settings.telegram_max_upload_mb * 1024 * 1024
            estimated_size = (
                (video.content_length or 0)
                + (
                    (resolved.best_audio().content_length or 0)
                    if not video.has_audio and resolved.best_audio()
                    else 0
                )
            ) or None

            return DownloadResult(
                job_id=job_id,
                file_path=output,
                target_height=target_height,
                selected_format=selected_format,
                estimated_size=estimated_size,
                actual_size=probe.size_bytes,
                exceeds_planning_limit=probe.size_bytes > max_size_bytes,
                probe=probe,
            )
        except Exception:
            if output.exists():
                output.unlink(missing_ok=True)
            raise
