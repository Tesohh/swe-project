FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# the build context is the repo root, because every service installs ./common
WORKDIR /srv/queues

COPY common /srv/common
COPY queues/pyproject.toml queues/uv.lock ./
RUN uv sync --frozen --no-dev

COPY queues/src ./src

EXPOSE 8000

CMD ["uv", "run", "--frozen", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
