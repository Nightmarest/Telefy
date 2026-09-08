# Multi-stage: uv builds the venv, slim runtime carries only what's needed.
FROM ghcr.io/astral-sh/uv:0.5-python3.12-bookworm-slim AS build

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install deps first (best cache hit)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Then install the project itself
COPY bot ./bot
COPY README.md ./README.md
RUN uv sync --frozen --no-dev


FROM python:3.12-slim-bookworm AS runtime

# Pillow needs a few shared libs at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo zlib1g libfreetype6 libtiff6 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root
RUN useradd --create-home --uid 10001 bot
WORKDIR /app

COPY --from=build --chown=bot:bot /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Mosaic cache lives here — mount a volume to keep it across restarts.
RUN mkdir -p /app/.claude && chown bot:bot /app/.claude
VOLUME ["/app/.claude"]

USER bot

CMD ["python", "-m", "bot"]
