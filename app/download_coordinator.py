from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .download_engine import DownloadResult, VideoDownloadEngine
from .reddit_support import RedditVideoDownloadEngine, RedditVideoResolver
from .url_validator import is_reddit_url
from .video_analyzer import (
    DownloadPlan,
    MAX_PLANNING_SIZE_BYTES,
    TARGET_RESOLUTIONS,
    available_resolutions,
    build_download_plan,
)
from .video_analyzer import VideoMetadataAnalyzer


@dataclass(frozen=True)
class DownloadOutcome:
    result: DownloadResult
    attempted_heights: tuple[int, ...]
    fallback_count: int
    available_heights: tuple[int, ...]


class VideoDownloadCoordinator:
    """Download the highest supported target, falling back only after a real size check."""

    def __init__(
        self,
        *,
        analyzer: VideoMetadataAnalyzer | None = None,
        downloader: VideoDownloadEngine | None = None,
        reddit_resolver: RedditVideoResolver | None = None,
        reddit_downloader: RedditVideoDownloadEngine | None = None,
        max_size_bytes: int = MAX_PLANNING_SIZE_BYTES,
    ) -> None:
        self.analyzer = analyzer or VideoMetadataAnalyzer()
        self.downloader = downloader or VideoDownloadEngine()
        self.reddit_resolver = reddit_resolver or RedditVideoResolver()
        self.reddit_downloader = reddit_downloader or RedditVideoDownloadEngine()
        self.max_size_bytes = max_size_bytes

    @staticmethod
    def _lower_targets(current_height: int, available: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(
            height
            for height in available
            if height < current_height
        )

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

    def _download_reddit(self, url: str, *, job_id: str) -> DownloadOutcome:
        resolved = self.reddit_resolver.resolve(url)
        supported_heights = resolved.available_heights
        if not supported_heights:
            raise ValueError("No supported Reddit video resolution at 480p or higher")

        attempts: list[int] = []
        current_height = next(
            height for height in TARGET_RESOLUTIONS
            if height in supported_heights
        )

        while True:
            attempts.append(current_height)
            result = self.reddit_downloader.download(
                resolved,
                current_height,
                job_id=job_id,
            )

            if result.actual_size <= self.max_size_bytes:
                return DownloadOutcome(
                    result=result,
                    attempted_heights=tuple(attempts),
                    fallback_count=len(attempts) - 1,
                    available_heights=supported_heights,
                )

            next_heights = tuple(
                height
                for height in supported_heights
                if height < current_height
            )
            if not next_heights:
                return DownloadOutcome(
                    result=result,
                    attempted_heights=tuple(attempts),
                    fallback_count=len(attempts) - 1,
                    available_heights=supported_heights,
                )

            current_height = next_heights[0]

    def download(self, url: str, *, job_id: str) -> DownloadOutcome:
        if is_reddit_url(url):
            return self._download_reddit(url, job_id=job_id)

        analysis = self.analyzer.analyze(url)
        supported_heights = available_resolutions(analysis)
        if not supported_heights:
            raise ValueError("No supported video format at 480p or higher")

        # The initial plan is always the highest supported resolution.
        current_plan = build_download_plan(
            analysis,
            max_size_bytes=self.max_size_bytes,
            targets=TARGET_RESOLUTIONS,
        )
        attempts: list[int] = []

        while True:
            attempts.append(current_plan.target_height)
            result = self.downloader.download(url, current_plan, job_id=job_id)

            if result.actual_size <= self.max_size_bytes:
                return DownloadOutcome(
                    result=result,
                    attempted_heights=tuple(attempts),
                    fallback_count=len(attempts) - 1,
                    available_heights=supported_heights,
                )

            next_plan = self._next_plan(analysis, current_plan.target_height, supported_heights)
            if next_plan is None:
                return DownloadOutcome(
                    result=result,
                    attempted_heights=tuple(attempts),
                    fallback_count=len(attempts) - 1,
                    available_heights=supported_heights,
                )

            current_plan = next_plan
