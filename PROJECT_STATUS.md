# Telegram Video Bot — Current Repository State

## Production architecture

The Blitz target is a single lightweight Python container:

- Flask provides the public HTTP service.
- python-telegram-bot handles Telegram updates.
- Telegram webhook delivery is used; no long polling runner is included.
- yt-dlp is the only media acquisition engine.
- FFmpeg/FFprobe are installed as system packages for media merging and validation.
- Telegram Cloud Bot API is used, with a 50 MB upload limit.
- Optional Netscape-format cookies can be supplied to yt-dlp.

## Removed deployment blockers

The repository no longer builds or bundles:

- TDLib / Telegram Local Bot API
- CMake / native C++ Telegram API compilation
- Invidious Companion
- Camoufox
- Playwright
- bgutil POT provider
- custom Telegram polling runtime
- Piped YouTube runtime

This removes the native C++ build stage that exhausted Blitz builder memory and removes the browser-backed YouTube Companion process.

## Quality policy

The source is inspected for 1080p, 720p, and 480p support. The highest source-supported target is downloaded first. The actual output size is checked after download. When it exceeds 50 MB, the next lower supported target is attempted. If 480p still exceeds 50 MB, the bot does not upload the file.

## Blitz verification boundary

CI can prove that the Python test suite, Docker build, FFmpeg availability, Gunicorn WSGI import, Compose configuration, webhook validation, and runtime files are correct.

CI cannot prove that a particular live YouTube URL succeeds from Blitz. That requires a real deployed test and, when YouTube requires authentication, a valid cookie file supplied to the running app.
