from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yt_dlp import YoutubeDL

MAX_VIDEO_SIZE_MB = 2000
MAX_PLANNING_SIZE_BYTES = MAX_VIDEO_SIZE_MB * 1024 * 1024
TARGET_RESOLUTIONS = (1080, 720, 480)


@dataclass(frozen=True)
class FormatCandidate:
    format_id: str
    height: int | None
    has_video: bool
    has_audio: bool
    ext: str | None
    filesize: int | None
    filesize_approx: int | None
    vbr: float | None
    abr: float | None
    tbr: float | None
    width: int | None = None

    @property
    def estimated_size(self) -> int | None:
        return self.filesize if self.filesize is not None else self.filesize_approx

    @property
    def quality_level(self) -> int | None:
        # Landscape: 1920x1080 -> 1080p
        # Portrait: 1080x1920 -> 1080p
        if self.width is not None and self.height is not None:
            return min(self.width, self.height)
        return self.height


@dataclass(frozen=True)
class DownloadPlan:
    target_height: int
    format_selector: str
    estimated_size: int | None
    exact_size_known: bool
    source_has_target_resolution: bool
    requires_size_reduction: bool


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _float_or_none(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) else None


def _parse_format(raw: dict[str, Any]) -> FormatCandidate:
    vcodec = raw.get("vcodec")
    acodec = raw.get("acodec")
    return FormatCandidate(
        format_id=str(raw.get("format_id", "")),
        height=_int_or_none(raw.get("height")),
        has_video=bool(vcodec and vcodec != "none"),
        has_audio=bool(acodec and acodec != "none"),
        ext=raw.get("ext"),
        filesize=_int_or_none(raw.get("filesize")),
        filesize_approx=_int_or_none(raw.get("filesize_approx")),
        vbr=_float_or_none(raw.get("vbr")),
        abr=_float_or_none(raw.get("abr")),
        tbr=_float_or_none(raw.get("tbr")),
        width=_int_or_none(raw.get("width")),
    )


class VideoMetadataAnalyzer:
    """Extract video metadata and available target resolutions without downloading."""

    def __init__(self, *, ydl_opts: dict[str, Any] | None = None) -> None:
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "js_runtimes": {"node": {}},
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        }
        if ydl_opts:
            options.update(ydl_opts)
        self._ydl_opts = options

    def analyze(self, url: str) -> dict[str, Any]:
        with YoutubeDL(self._ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = [_parse_format(item) for item in (info.get("formats") or [])]
        available_resolutions = tuple(
            target
            for target in TARGET_RESOLUTIONS
            if any(item.has_video and item.quality_level == target for item in formats)
        )
        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "duration": info.get("duration"),
            "webpage_url": info.get("webpage_url") or url,
            "formats": formats,
            "available_resolutions": available_resolutions,
        }


def available_resolutions(analysis: dict[str, Any]) -> tuple[int, ...]:
    """Return supported target resolutions, highest first, from extracted formats."""
    existing = analysis.get("available_resolutions")
    if isinstance(existing, (tuple, list)):
        return tuple(int(item) for item in existing if int(item) in TARGET_RESOLUTIONS)

    formats = analysis.get("formats") or []
    parsed = [item if isinstance(item, FormatCandidate) else _parse_format(item) for item in formats]
    return tuple(
        target
        for target in TARGET_RESOLUTIONS
        if any(item.has_video and item.quality_level == target for item in parsed)
    )


def _choose_audio_format(formats: list[FormatCandidate]) -> FormatCandidate | None:
    candidates = [item for item in formats if item.has_audio and not item.has_video]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.abr or 0)


def _bitrate_estimate_bytes(*, bitrate_kbps: float | None, duration_seconds: float | int | None) -> int | None:
    if bitrate_kbps is None or duration_seconds is None or duration_seconds <= 0:
        return None
    return int(bitrate_kbps * 1000 / 8 * float(duration_seconds))


def _format_estimated_size(
    item: FormatCandidate, *, duration_seconds: float | int | None, is_audio: bool = False
) -> tuple[int | None, bool]:
    if item.filesize is not None:
        return item.filesize, True
    if item.filesize_approx is not None:
        return item.filesize_approx, False

    bitrate = item.abr if is_audio else item.tbr
    estimated = _bitrate_estimate_bytes(bitrate_kbps=bitrate, duration_seconds=duration_seconds)
    return estimated, False


def _combined_estimated_size(
    video: FormatCandidate,
    audio: FormatCandidate | None,
    *,
    duration_seconds: float | int | None,
) -> tuple[int | None, bool]:
    if video.has_audio:
        return _format_estimated_size(video, duration_seconds=duration_seconds)

    if audio is None:
        return _format_estimated_size(video, duration_seconds=duration_seconds)

    video_size, video_exact = _format_estimated_size(video, duration_seconds=duration_seconds)
    audio_size, audio_exact = _format_estimated_size(audio, duration_seconds=duration_seconds, is_audio=True)
    if video_size is None or audio_size is None:
        return None, False
    return video_size + audio_size, video_exact and audio_exact


def _plan_for_target(
    analysis: dict[str, Any],
    parsed: list[FormatCandidate],
    target: int,
    *,
    max_size_bytes: int,
) -> DownloadPlan | None:
    target_formats = [item for item in parsed if item.has_video and item.quality_level == target]
    if not target_formats:
        return None

    audio_candidates = [item for item in parsed if item.has_audio and not item.has_video]

    def selector_for(video: FormatCandidate, audio: FormatCandidate | None) -> str | None:
        if video.has_audio:
            return video.format_id
        if audio is None:
            return None
        return f"{video.format_id}+{audio.format_id}"

    target_formats.sort(key=lambda item: (item.vbr or 0, item.tbr or 0), reverse=True)

    # Quality selection is based on actual source availability, not estimated size.
    # The coordinator will perform the real download and only then fall back when
    # the produced file exceeds the 2000 MB limit.
    for video in target_formats:
        options = [None] if video.has_audio else sorted(
            audio_candidates, key=lambda item: item.abr or 0, reverse=True
        )
        for audio in options:
            selector = selector_for(video, audio)
            if selector is None:
                continue
            estimated_size, exact_size_known = _combined_estimated_size(
                video, audio, duration_seconds=analysis.get("duration")
            )
            return DownloadPlan(
                target_height=target,
                format_selector=selector,
                estimated_size=estimated_size,
                exact_size_known=exact_size_known,
                source_has_target_resolution=True,
                requires_size_reduction=(
                    estimated_size is not None and estimated_size > max_size_bytes
                ),
            )

    return None


def build_download_plan(
    analysis: dict[str, Any],
    *,
    max_size_bytes: int = MAX_PLANNING_SIZE_BYTES,
    targets: tuple[int, ...] = TARGET_RESOLUTIONS,
) -> DownloadPlan:
    formats = analysis.get("formats") or []
    parsed = [item if isinstance(item, FormatCandidate) else _parse_format(item) for item in formats]

    # First inspect all requested quality levels and select the highest one that
    # the source actually provides. Estimated file size never causes us to skip
    # a supported quality; the 2000 MB rule is enforced after the real download.
    normalized_targets = tuple(height for height in targets if height in TARGET_RESOLUTIONS)
    for target in normalized_targets:
        plan = _plan_for_target(
            analysis, parsed, target, max_size_bytes=max_size_bytes
        )
        if plan is not None:
            return plan

    raise ValueError("No supported video format at 480p or higher")
