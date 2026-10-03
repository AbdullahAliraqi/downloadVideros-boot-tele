from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .download_engine import DownloadResult, DownloadTooLargeError, VideoDownloadEngine
from .url_validator import platform_for_url
from .video_analyzer import (
    DownloadPlan,
    MAX_PLANNING_SIZE_BYTES,
    TARGET_RESOLUTIONS,
    VideoMetadataAnalyzer,
    available_resolutions,
    build_download_plan,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadOutcome:
    result: DownloadResult
    attempted_heights: tuple[int, ...]
    fallback_count: int
    available_heights: tuple[int, ...]


class VideoDownloadCoordinator:
    """Choose the highest source-supported quality and enforce the real 50 MB limit."""

    def __init__(
        self,
        *,
        analyzer: VideoMetadataAnalyzer | None = None,
        downloader: VideoDownloadEngine | None = None,
        max_size_bytes: int = MAX_PLANNING_SIZE_BYTES,
    ) -> None:
        self.analyzer = analyzer or VideoMetadataAnalyzer()
        self.downloader = downloader or VideoDownloadEngine()
        self.max_size_bytes = max_size_bytes

    @staticmethod
    def _lower_targets(
        current_height: int,
        available: tuple[int, ...],
    ) -> tuple[int, ...]:
        return tuple(height for height in available if height < current_height)

    def _next_plan(
        self,
        analysis: dict[str, Any],
        current_height: int,
        supported_heights: tuple[int, ...],
    ) -> DownloadPlan | None:
        targets = self._lower_targets(current_height, supported_heights)
        if not targets:
            return None
        return build_download_plan(
            analysis,
            max_size_bytes=self.max_size_bytes,
            targets=targets,
        )

    def download(self, url: str, *, job_id: str) -> DownloadOutcome:
        platform = platform_for_url(url)
        if platform is None:
            raise ValueError("Unsupported video URL")

        analysis = self.analyzer.analyze(url)
        supported_heights = available_resolutions(analysis)
        if not supported_heights:
            raise ValueError("No supported video format at 480p or higher")

        current_plan = build_download_plan(
            analysis,
            max_size_bytes=self.max_size_bytes,
            targets=TARGET_RESOLUTIONS,
        )
        attempts: list[int] = []

        while True:
            attempts.append(current_plan.target_height)
            try:
                result = self.downloader.download(
                    url,
                    current_plan,
                    job_id=job_id,
                )
            except DownloadTooLargeError:
                next_plan = self._next_plan(
                    analysis,
                    current_plan.target_height,
                    supported_heights,
                )
                if next_plan is None:
                    raise
                current_plan = next_plan
                continue

            if result.actual_size <= self.max_size_bytes:
                return DownloadOutcome(
                    result=result,
                    attempted_heights=tuple(attempts),
                    fallback_count=len(attempts) - 1,
                    available_heights=supported_heights,
                )

            next_plan = self._next_plan(
                analysis,
                current_plan.target_height,
                supported_heights,
            )
            if next_plan is None:
                return DownloadOutcome(
                    result=result,
                    attempted_heights=tuple(attempts),
                    fallback_count=len(attempts) - 1,
                    available_heights=supported_heights,
                )

            current_plan = next_plan
