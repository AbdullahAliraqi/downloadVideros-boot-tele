FROM debian:bookworm-slim AS telegram-bot-api-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        gperf \
        git \
        libssl-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 --recursive https://github.com/tdlib/telegram-bot-api.git telegram-bot-api \
    && cmake -S telegram-bot-api -B telegram-bot-api/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/telegram-bot-api \
    && cmake --build telegram-bot-api/build --target install -j"$(nproc)" \
    && strip /opt/telegram-bot-api/bin/telegram-bot-api

FROM quay.io/invidious/invidious-companion:latest AS youtube-companion

FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BLITZ_SINGLE_CONTAINER=true \
    YOUTUBE_COMPANION_BASE_URL=http://127.0.0.1:8282/companion

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        git \
        libssl3 \
        zlib1g \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=telegram-bot-api-builder /opt/telegram-bot-api/bin/telegram-bot-api /usr/local/bin/telegram-bot-api
COPY --from=youtube-companion /app/invidious_companion /usr/local/bin/invidious_companion
COPY --from=node:24-bookworm-slim /usr/local/ /usr/local/

RUN node --version \
    && git clone --depth 1 --single-branch --branch 2.0.1 \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-ytdlp-pot-provider \
    && cd /opt/bgutil-ytdlp-pot-provider/server \
    && npm ci \
    && npx tsc

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests
COPY scripts ./scripts
COPY .env.example .env.example

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app /data/downloads /data/telegram-bot-api /data/youtube-companion /var/tmp/youtubei.js \
    && chmod +x /app/scripts/blitz_entrypoint.sh \
    && chown -R appuser:appuser /app /data /var/tmp/youtubei.js

USER appuser

VOLUME ["/data/downloads", "/data/telegram-bot-api", "/data/youtube-companion", "/var/tmp/youtubei.js"]

EXPOSE 8000

ENTRYPOINT ["/app/scripts/blitz_entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
