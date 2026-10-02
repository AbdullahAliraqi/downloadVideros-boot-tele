from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import httpx
from .config import settings
from .download_engine import DownloadResult
from .media_tools import FFmpegTools

COBALT_API_URLS = (
    "https://cobalt-alpha.wolfy.love",
    "https://grapefruit.clxxped.lol",
    "https://nuko-c.meowing.de",
)
COBALT_TIMEOUT = httpx.Timeout(120.0)
COBALT_DOWNLOAD_TIMEOUT = httpx.Timeout(600.0)

class CobaltUnavailableError(RuntimeError):
    pass

@dataclass(frozen=True)
class CobaltMedia:
    api_url: str
    media_url: str
    filename: str
    requested_height: int

def _safe_filename(value: str) -> str:
    value = re.sub(r"[^\w\-. ]+", "", value, flags=re.UNICODE).strip()
    return value[:120] or "video"

class CobaltResolver:
    def __init__(self, api_urls: tuple[str, ...] = COBALT_API_URLS) -> None:
        self.api_urls = api_urls

    def resolve(self, url: str, target_height: int) -> CobaltMedia:
        errors: list[str] = []
        for api_url in self.api_urls:
            try:
                response = httpx.post(
                    api_url.rstrip("/") + "/",
                    json={
                        "url": url,
                        "videoQuality": str(target_height),
                        "downloadMode": "auto",
                        "videoContainer": "mp4",
                        "filenameStyle": "basic",
                        "alwaysProxy": True,
                        "localProcessing": "disabled",
                    },
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "User-Agent": "DownloadsVideosBot/1.0",
                    },
                    timeout=COBALT_TIMEOUT,
                    follow_redirects=True,
                )
                response.raise_for_status()
                payload = response.json()
                status = payload.get("status") if isinstance(payload, dict) else None
                if status not in {"tunnel", "redirect"}:
                    raise CobaltUnavailableError(
                        f"Cobalt returned status {status or 'unknown'}"
                    )
                media_url = str(payload.get("url") or "").strip()
                if not media_url:
                    raise CobaltUnavailableError("Cobalt returned no media URL")
                return CobaltMedia(
                    api_url=api_url,
                    media_url=media_url,
                    filename=str(payload.get("filename") or "").strip(),
                    requested_height=target_height,
                )
            except (httpx.HTTPError, ValueError, CobaltUnavailableError) as exc:
                errors.append(f"{api_url}: {type(exc).__name__}")
        raise CobaltUnavailableError(
            "No public Cobalt instance accepted the request: " + "; ".join(errors)
        )

class CobaltVideoDownloadEngine:
    def __init__(self, *, ffmpeg_path: str | None = None, ffprobe_path: str | None = None) -> None:
        self.ffmpeg = FFmpegTools(ffmpeg_path, ffprobe_path)

    def download(self, media: CobaltMedia, *, job_id: str) -> DownloadResult:
        self.ffmpeg.check()
        root = Path(settings.download_root)
        job_dir = root / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        output = job_dir / (_safe_filename(Path(media.filename).stem or "video") + ".mp4")
        try:
            with httpx.stream(
                "GET",
                media.media_url,
                headers={"User-Agent": "DownloadsVideosBot/1.0"},
                timeout=COBALT_DOWNLOAD_TIMEOUT,
                follow_redirects=True,
            ) as response:
                response.raise_for_status()
                with output.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if chunk:
                            handle.write(chunk)
        except (httpx.HTTPError, OSError) as exc:
            raise CobaltUnavailableError(
                f"Cobalt media download failed: {type(exc).__name__}"
            ) from exc
        if not output.is_file() or output.stat().st_size <= 0:
            raise CobaltUnavailableError("Cobalt returned an empty file")
        probe = self.ffmpeg.probe(output)
        actual_height = probe.height or media.requested_height
        return DownloadResult(
            job_id=job_id,
            file_path=output,
            target_height=actual_height,
            selected_format=f"cobalt:{actual_height}p",
            estimated_size=None,
            actual_size=probe.size_bytes,
            exceeds_planning_limit=probe.size_bytes > 2000 * 1024 * 1024,
            probe=probe,
        )
