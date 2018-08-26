FROM debian:stretch-slim

RUN apt-get update && apt-get install -y \
    python3-requests \
    python3-flask \
    python3-twisted \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
WORKDIR /app
ENTRYPOINT ["python3", "main.py", "-p", "80"]
EXPOSE 80
