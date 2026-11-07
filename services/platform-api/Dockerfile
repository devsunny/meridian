# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_CACHE_DIR=/tmp/uv-cache UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src
COPY packages/connector-sdk /src/packages/connector-sdk
COPY services/platform-api/pyproject.toml services/platform-api/uv.lock /src/services/platform-api/
WORKDIR /src/services/platform-api
RUN uv sync --frozen --no-dev --no-editable --no-cache
COPY services/platform-api /src/services/platform-api

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    MERIDIAN_ENV=production \
    MERIDIAN_STORAGE_ROOT=/data/warehouse \
    MERIDIAN_LOG_DIR=/data/logs \
    MERIDIAN_FILE_ROOTS=/data \
    MERIDIAN_DATABASE_URL=postgresql+pg8000://meridian:meridian@postgres:5432/meridian

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 meridian \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin meridian \
 && mkdir -p /data/warehouse /data/logs /data/uploads \
 && chown -R meridian:meridian /data

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /src/services/platform-api/src /app/src
COPY packages/connector-sdk/README.md /app/CONNECTOR_SDK.md

WORKDIR /app
USER meridian
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"
CMD ["uvicorn", "meridian.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
