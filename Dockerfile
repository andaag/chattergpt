FROM python:3.11-slim

ENV PYTHONFAULTHANDLER=1 \
     PYTHONUNBUFFERED=1 \
     PYTHONDONTWRITEBYTECODE=1 \
     PIP_DISABLE_PIP_VERSION_CHECK=on

#RUN apt-get update && apt-get -y install ffmpeg

WORKDIR /app
COPY poetry.lock pyproject.toml ./
RUN pip install poetry
RUN poetry install
COPY *.py ./
COPY .env .env
CMD ["/usr/local/bin/poetry", "run", "python3", "app.py"]
