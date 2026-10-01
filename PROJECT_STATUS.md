# Telegram Video Bot — Repository State

This repository now contains the source files recovered from the project's v18 source overlay.

Recovered source files:
- `render.yaml`
- `tests/test_url_validator.py`
- `tests/test_v18_features.py`
- `tests/test_main.py`
- `tests/test_download_coordinator.py`
- `tests/test_video_analyzer.py`
- `app/video_analyzer.py`
- `app/reddit_support.py`
- `app/url_validator.py`
- `app/main.py`
- `app/download_coordinator.py`
- `app/local_runner.py`

Known runtime requirements/configuration from the project logs:
- Python 3.14
- FFmpeg / FFprobe
- yt-dlp with YouTube EJS support
- Local Telegram Bot API for the 2000 MB upload target
- Six supported platforms: YouTube, Facebook, Instagram, TikTok, X, Reddit
- Quality policy: start at highest supported target (1080p, then 720p, then 480p) and fall back after an actual size check when the 2000 MB limit is exceeded.

Important: this file records the recovered source set; packaging/runtime files not present in the source overlay (for example an exact Dockerfile/requirements snapshot) are intentionally not invented here.