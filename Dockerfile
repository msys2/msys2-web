FROM python:3.9-buster as build

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install "poetry==1.1.12"

COPY . /app
WORKDIR /app
RUN poetry config virtualenvs.in-project true
RUN poetry install --no-dev

FROM python:3.9-buster

COPY --from=build /app /app

RUN apt-get update && apt-get install -y \
    python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:80", "--timeout", "60", "app:app"]

EXPOSE 80
