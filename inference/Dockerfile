FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
ARG TORCH_VARIANT=cpu
RUN uv sync --frozen --no-dev --extra ${TORCH_VARIANT}

COPY src ./src

EXPOSE 8000

CMD ["uv", "run", "--frozen", "--no-sync", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
