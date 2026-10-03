from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

from .config import settings
from .media_tools import FFmpegTools, MediaProbeResult
from .video_analyzer import DownloadPlan
from .ydl_config import TELEGRAM_MAX_FILESIZE, build_ydl_opts


@dataclass(frozen=True)
class DownloadResult:
    job_id: str
    file_path: Path
    target_height: int
    selected_format: str
    estimated_size: int | None
    actual_size: int
    exceeds_planning_limit: bool
    probe: MediaProbeResult


class DownloadTooLargeError(RuntimeError):
    """Raised when yt-dlp refuses a source because of the Telegram size guard."""


class VideoDownloadEngine:
    def __init__(
        self,
        *,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
    ) -> None:
        self.ffmpeg = FFmpegTools(ffmpeg_path, ffprobe_path)


    def download(
        self,
        url: str,
        plan: DownloadPlan,
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

        clients = plan.youtube_clients or None
        use_cookies = plan.youtube_use_cookies
        options = build_ydl_opts(
            url,
            output_template=str(job_dir / "%(id)s.%(ext)s"),
            format_selector=plan.format_selector,
            youtube_clients=clients,
            use_cookies=use_cookies,
        )
        options.update(
            {
                "merge_output_format": "mp4",
                "ffmpeg_location": settings.ffmpeg_path,
                "max_filesize": TELEGRAM_MAX_FILESIZE,
            }
        )

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                result_code = ydl.download([url])
        except DownloadError as exc:
            message = str(exc)
            lowered = message.lower()
            if "max filesize" in lowered or "larger than the max" in lowered:
                raise DownloadTooLargeError(
                    f"Source/output exceeded the Telegram 50 MB guard: {message}"
                ) from exc
            if "sign in to confirm" in lowered or "not a bot" in lowered:
                raise RuntimeError(
                    "YouTube rejected the request as an automated/bot request "
                    "even with the configured lightweight client fallback."
                ) from exc
            raise RuntimeError(f"yt-dlp download failed: {message}") from exc

        if result_code not in (None, 0):
            raise RuntimeError(f"yt-dlp download failed with code {result_code}")


        candidates = [
            path
            for path in job_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in {
                ".mp4",
                ".mkv",
                ".webm",
                ".mov",
                ".avi",
            }
        ]
        if not candidates:
            raise FileNotFoundError(
                f"yt-dlp completed but no video file was found in {job_dir}"
            )

        output = max(candidates, key=lambda path: path.stat().st_size)
        probe = self.ffmpeg.probe(output)

        return DownloadResult(
            job_id=job_id,
            file_path=output,
            target_height=plan.target_height,
            selected_format=plan.format_selector,
            estimated_size=plan.estimated_size,
            actual_size=probe.size_bytes,
            exceeds_planning_limit=probe.size_bytes
            > settings.telegram_max_upload_mb * 1024 * 1024,
            probe=probe,
        )
