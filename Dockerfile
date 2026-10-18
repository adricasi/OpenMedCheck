# syntax=docker/dockerfile:1
# OpenMedCheck app image (T-016, AC-015.4). Synthetic patients only; not a medical device.
FROM ghcr.io/astral-sh/uv:0.13.1 AS uv

FROM python:3.12.15-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# README.md is the package readme declared in pyproject.toml, needed to build the project.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12.15-slim-bookworm
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin openmedcheck
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPENMEDCHECK_HOST=0.0.0.0 \
    OPENMEDCHECK_ALLOW_NONLOCAL=1 \
    OPENMEDCHECK_PUBLIC_HOSTS=localhost,127.0.0.1
# Binding 0.0.0.0 is only the container side; publish the port on 127.0.0.1 (see
# docker-compose.yml) to keep the app local.
USER openmedcheck
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request as u; p = os.environ.get('OPENMEDCHECK_PORT') or os.environ.get('PORT', '8000'); u.urlopen(f'http://127.0.0.1:{p}/healthz', timeout=4)"]
CMD ["openmedcheck"]
