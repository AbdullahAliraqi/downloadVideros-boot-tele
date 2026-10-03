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

FROM denoland/deno:bin-2.9.2 AS deno-bin

# Build Invidious Companion from the maintainer's Camoufox PO-token PR.
FROM debian:bookworm-slim AS youtube-companion-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        jq \
        unzip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deno-bin /deno /usr/local/bin/deno

WORKDIR /src
RUN git clone --depth 1 --branch camoufox-support-potoken https://github.com/unixfox/invidious-companion.git invidious-companion \
    && cd invidious-companion \
    && test "$(git rev-parse HEAD)" = "95a84404e0dd70fc5a6143fc245336bc7e609fc4" \
    && deno task compile \
    && tag="$(jq -er '.camoufox.linux.x86_64.version' dependencies.json)" \
    && version="${tag#v}" \
    && checksum="$(jq -er '.camoufox.linux.x86_64.sha256' dependencies.json)" \
    && curl -fsSL --output /tmp/camoufox.zip \
        "https://github.com/daijro/camoufox/releases/download/${tag}/camoufox-${version}-lin.x86_64.zip" \
    && echo "${checksum}  /tmp/camoufox.zip" | sha256sum -c - \
    && mkdir -p /opt/camoufox \
    && unzip -q /tmp/camoufox.zip -d /opt/camoufox \
    && test -x /opt/camoufox/camoufox-bin \
    && printf '{"version":"%s","release":"%s"}\n' "${version%%-*}" "${version#*-}" > /opt/camoufox/version.json \
    && rm /tmp/camoufox.zip

FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BLITZ_SINGLE_CONTAINER=true \
    YOUTUBE_COMPANION_BASE_URL=http://127.0.0.1:8282/companion \
    CAMOUFOX_INSTALL_DIR=/opt/camoufox \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    HOME=/var/tmp/youtubei.js/home \
    TMPDIR=/var/tmp/youtubei.js/tmp \
    XDG_CACHE_HOME=/var/tmp/youtubei.js/xdg-cache \
    XDG_DATA_HOME=/var/tmp/youtubei.js/xdg-data

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        git \
        libssl3 \
        zlib1g \
        libstdc++6 \
        libasound2 \
        libatk1.0-0 \
        libcairo-gobject2 \
        libcairo2 \
        libdbus-1-3 \
        libdbus-glib-1-2 \
        libfontconfig1 \
        libfreetype6 \
        libgdk-pixbuf-2.0-0 \
        libglib2.0-0 \
        libgtk-3-0 \
        libharfbuzz0b \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libx11-6 \
        libx11-xcb1 \
        libxcb-shm0 \
        libxcb1 \
        libxcomposite1 \
        libxcursor1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxrandr2 \
        libxrender1 \
        libxtst6 \
        libxkbcommon0 \
        libdrm2 \
        libgbm1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=telegram-bot-api-builder /opt/telegram-bot-api/bin/telegram-bot-api /usr/local/bin/telegram-bot-api
COPY --from=youtube-companion-builder /src/invidious-companion/invidious_companion /usr/local/bin/invidious_companion
COPY --from=youtube-companion-builder /opt/camoufox /opt/camoufox
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
