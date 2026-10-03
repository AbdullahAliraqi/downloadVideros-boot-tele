FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    TELEGRAM_MAX_UPLOAD_MB=50 \
    FFMPEG_PATH=ffmpeg \
    FFPROBE_PATH=ffprobe \
    DOWNLOAD_ROOT=/data/downloads \
    YTDLP_COOKIES_FILE=/app/cookies.txt

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY wsgi.py .
COPY cookies.txt .
COPY .env.example .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/downloads \
    && chown -R appuser:appuser /app /data \
    && chmod 644 /app/cookies.txt

USER appuser

VOLUME ["/data/downloads"]

EXPOSE 8000

CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "120"]
