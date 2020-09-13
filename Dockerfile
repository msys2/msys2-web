FROM ubuntu:focal

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install "poetry==1.0.10"

COPY . /app
WORKDIR /app
RUN poetry install --no-dev

ENTRYPOINT ["poetry","run", "uvicorn", "--proxy-headers", "--host", "0.0.0.0", "--port", "80", "app:app"]
EXPOSE 80
