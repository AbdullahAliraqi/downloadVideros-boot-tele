from __future__ import annotations

from datetime import timedelta


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    value = float(size_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
    return f"{value:.2f} TB"


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "غير معروف"
    total = max(0, int(round(float(seconds))))
    return str(timedelta(seconds=total))
