from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from .config import settings
from .media_tools import FFmpegTools, MediaProbeResult
from .url_validator import platform_for_url
from .video_analyzer import DownloadPlan


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

        options = {
            "format": plan.format_selector,
            "outtmpl": str(job_dir / "%(id)s.%(ext)s"),
            "merge_output_format": "mp4",
            "ffmpeg_location": settings.ffmpeg_path,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "overwrites": True,
            "js_runtimes": {"node": {}},
            "extractor_args": {
                "youtubepot-bgutilhttp": {"base_url": "http://127.0.0.1:4416"},
            },
        }

        if settings.ytdlp_proxy_url:
            options["proxy"] = settings.ytdlp_proxy_url
        if settings.ytdlp_cookies_file and platform_for_url(url) == "YouTube":
            options["cookiefile"] = settings.ytdlp_cookies_file

        with yt_dlp.YoutubeDL(options) as ydl:
            result_code = ydl.download([url])
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
