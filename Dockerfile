FROM python:3.11-slim-bullseye

RUN python -m pip install "poetry==1.5.1"

COPY . /app
WORKDIR /app
RUN poetry config virtualenvs.in-project true
RUN poetry install --only main

ENTRYPOINT ["poetry", "run", "gunicorn", "-k", "uvicorn.workers.UvicornWorker", "--access-logfile", "-", "--bind", "0.0.0.0:80", "--timeout", "60", "app:app"]

EXPOSE 80
