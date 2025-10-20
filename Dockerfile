FROM python:3.14-slim-trixie

RUN apt-get update && apt-get install -y --no-install-recommends \
    media-types \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install "uv==0.9.3"

COPY . /app
WORKDIR /app

RUN uv sync --locked --no-dev

ENTRYPOINT ["uv", "run", "gunicorn", "-k", "uvicorn_worker.UvicornWorker", "--access-logfile", "-", "--bind", "0.0.0.0:80", "--timeout", "60", "app:app"]

EXPOSE 80
