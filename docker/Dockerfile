# Chamber Scribe — production container.
#
# Lives in docker/, but must be built with the repo root as context (not
# this folder), since COPY . . below needs the whole project:
#   docker build -f docker/Dockerfile -t chamber-scribe:latest .
# docker-compose.yml (same folder) already does this via its
# `context: .. / dockerfile: docker/Dockerfile` build block.
#
# Builds one image used by all three processes (pipeline, API) — which
# process runs is decided by the command, not the image (see
# docker-compose.yml). This keeps the image simple: one Dockerfile, one
# set of dependencies, no drift between what the pipeline and the API run.
#
# GPU note: this image installs the CPU build of torch, so Whisper runs on
# CPU here — the simplest thing that works everywhere Docker runs. If you
# need GPU transcription in a container, swap the base image for an
# nvidia/cuda image and install a CUDA torch build instead (see README).

FROM python:3.12-slim

# ffmpeg: required by the downloader/transcriber for audio extraction.
# curl: used by the HEALTHCHECK below.
# ca-certificates: needed for httpx/TLS to the Senate/House portals.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer is cached unless requirements
# change — code changes below won't force a full dependency reinstall.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY . .

# Don't run as root — standard hardening for a container that makes
# outbound network calls to third-party sites (the Senate/House portals).
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p storage/audio storage/captions \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
ENV HF_HUB_DISABLE_SYMLINKS_WARNING=1

EXPOSE 8000

# No default HEALTHCHECK here — it depends on which command this container
# is running (see docker-compose.yml, which adds one to the api service
# only, hitting /health). /health already reports on the pipeline loops
# too via their Mongo heartbeats, so one healthcheck on the api container
# covers the whole system.

# Default command runs the pipeline (scraper + downloader + transcriber
# loops). docker-compose.yml overrides this for the api service.
CMD ["python", "main.py"]
