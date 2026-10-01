from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import settings


@dataclass(frozen=True)
class MediaProbeResult:
    path: Path
    size_bytes: int
    duration_seconds: float | None
    width: int | None = None
    height: int | None = None


class FFmpegTools:
    def __init__(
        self,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
    ) -> None:
        self.ffmpeg_path = ffmpeg_path or settings.ffmpeg_path
        self.ffprobe_path = ffprobe_path or settings.ffprobe_path

    def check(self) -> None:
        for executable in (self.ffmpeg_path, self.ffprobe_path):
            result = subprocess.run(
                [executable, "-version"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Required media tool is unavailable: {executable}")

    def probe(self, path: Path) -> MediaProbeResult:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)

        completed = subprocess.run(
            [
                self.ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip() or "ffprobe failed"
            )

        payload = json.loads(completed.stdout or "{}")
        streams = payload.get("streams") or []
        video = next(
            (
                stream
                for stream in streams
                if stream.get("codec_type") == "video"
            ),
            {},
        )

        duration_raw = (payload.get("format") or {}).get("duration")
        duration = None
        if isinstance(duration_raw, (int, float, str)):
            try:
                duration = float(duration_raw)
            except ValueError:
                duration = None

        width = video.get("width")
        height = video.get("height")

        return MediaProbeResult(
            path=path,
            size_bytes=path.stat().st_size,
            duration_seconds=duration,
            width=width if isinstance(width, int) else None,
            height=height if isinstance(height, int) else None,
        )
