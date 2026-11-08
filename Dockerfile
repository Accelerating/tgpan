FROM node:22-bookworm-slim AS frontend
RUN corepack enable && corepack prepare pnpm@10.32.1 --activate
WORKDIR /web
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
COPY frontend/patches ./patches
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.13-slim-bookworm AS backend
COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --python /usr/local/bin/python3.13
COPY backend/app ./app
COPY --from=frontend /web/dist ./static
RUN groupadd --gid 10001 tgpan && useradd --uid 10001 --gid tgpan --no-create-home tgpan && mkdir /data && chown tgpan:tgpan /data
ENV TGPAN_DATA_DIR=/data TGPAN_STATIC_DIR=/app/static PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER tgpan
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers"]
