FROM ghcr.io/astral-sh/uv:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    media-types \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
WORKDIR /app

RUN uv sync --python 3.14 --locked --no-dev --compile-bytecode

ENTRYPOINT ["uv", "run", "--no-sync", "gunicorn", "-k", "uvicorn_worker.UvicornWorker", "--access-logfile", "-", "--bind", "0.0.0.0:80", "--timeout", "60", "app:app"]

EXPOSE 80
