FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-core fonts-noto-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
COPY adapters ./adapters
COPY PROVIDER_CONTRACTS.md ./
RUN pip install --no-cache-dir ".[media]" yt-dlp

VOLUME ["/data"]
EXPOSE 8787

CMD ["newsroom-pipeline", "--root", "/data", "--config", "/app/configs/default.json", "serve", "--host", "0.0.0.0", "--port", "8787"]
