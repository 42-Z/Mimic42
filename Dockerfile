# syntax=docker/dockerfile:1
# Mimic42 backend: FastAPI + Telethon userbot runtimes.
#
# Single uvicorn process on purpose (no --workers): AgentManager keeps live
# Telethon clients in process memory, two replicas would conflict sessions.

FROM python:3.13-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

WORKDIR /app

# Dependency layer first for cache reuse. README.md must be present:
# [project].readme in pyproject.toml makes hatchling require it at build time.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=README.md,target=README.md \
    uv sync --locked --no-install-project --no-dev --no-editable

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


FROM python:3.13-slim-trixie AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Same base image as the builder stage: the venv stores absolute paths.
COPY --from=builder /app/.venv /app/.venv

# Non-root user with a writable workdir: telethon_client.py falls back to a
# file-based .session in CWD when no session string is configured.
RUN useradd --create-home --uid 10000 app \
    && mkdir -p /app/data \
    && chown app:app /app/data

USER app
WORKDIR /app/data

EXPOSE 8000

# No curl in slim images: probe with the venv python itself.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').getcode() == 200 else 1)"]

CMD ["python", "-m", "uvicorn", "mimic42.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
