# syntax=docker/dockerfile:1.7
FROM node:24-alpine AS frontend
WORKDIR /src/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.13-slim AS wheel
WORKDIR /src
COPY pyproject.toml README.md ./
COPY backend/ ./backend/
COPY --from=frontend /src/frontend/dist/ ./backend/voice_console/static/
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 voiceconsole \
    && useradd --uid 10001 --gid voiceconsole --create-home voiceconsole \
    && mkdir -p /config /data \
    && chown -R voiceconsole:voiceconsole /config /data
COPY --from=wheel /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
WORKDIR /app
USER 10001:10001
EXPOSE 8787
VOLUME ["/config", "/data"]
HEALTHCHECK --interval=20s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=2).read()"]
CMD ["voice-console", "serve", "--config", "/config/voice.yaml", "--targets", "/config/targets.yaml", "--env", "/config/.env", "--static-dir", "auto"]
