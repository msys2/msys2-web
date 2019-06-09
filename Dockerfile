FROM debian:buster-slim

RUN apt-get update && apt-get install -y \
    python3-requests \
    python3-flask \
    gunicorn3 \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
WORKDIR /app
ENTRYPOINT ["gunicorn3", "-w1", "-b0.0.0.0:80", "main:app"]
EXPOSE 80
