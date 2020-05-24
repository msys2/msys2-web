FROM ubuntu:focal

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install "poetry==1.0.5"

COPY . /app
WORKDIR /app
RUN poetry install --no-dev

ENTRYPOINT ["poetry","run", "gunicorn", "-w1", "-b0.0.0.0:80", "app.main:app"]
EXPOSE 80
