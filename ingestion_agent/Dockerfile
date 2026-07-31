# RazTech AI Content Pipeline — Ingestion Agent
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INGESTION_CONTENT_ROOT=/content \
    INGESTION_FAILED_ROOT=/failed

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY pyproject.toml README.md /app/
COPY config /app/config
COPY src /app/src

RUN pip install --no-cache-dir -e .

# Default watch / storage mount points
RUN mkdir -p /streams/recordings /obs/output /imports /content /failed

VOLUME ["/streams/recordings", "/obs/output", "/imports", "/content", "/failed"]

ENTRYPOINT ["ingestion-agent"]
CMD ["watch"]
