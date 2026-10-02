FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

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
COPY .env.example .env.example

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/downloads \
    && chown -R appuser:appuser /app /data/downloads

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "node /opt/bgutil-ytdlp-pot-provider/server/build/main.js --port 4416 & exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
