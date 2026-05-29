FROM python:3.12-slim-bookworm

# uv as a single static binary, copied from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# git is needed only to fetch the git-based fast-flights dep during the
# consent-fix experiment (thoughtpunch fork). Remove once we pin a real release.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for better layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Then the project itself
COPY app/ ./app/
RUN uv sync --frozen --no-dev

# Overridden per-service in compose.yml
CMD ["python", "-m", "app.bot"]
