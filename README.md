# Chamber Scribe

Scrapes Michigan legislative hearing videos (Senate + House), downloads their audio/captions, transcribes them, and serves the transcripts over a REST API.

![Architecture](design.svg)

## About me

Hi there, I'm Isabel, most call me Izzy, welcome to my readME! As you go through the code, you'll see that I have a strong background in software development and a passion for creating efficient and scalable systems. I enjoy tackling complex problems and finding elegant solutions that make a real impact.
Please don't hesitate to ask any question, excited to chat!

- Email: [isabellopez0919@gmail.com](mailto:isabellopez0919@gmail.com)
- GitHub: [https://github.com/ilopez19](https://github.com/ilopez19)
- LinkedIn: [https://www.linkedin.com/in/isabellopez0919](https://www.linkedin.com/in/isabellopez19/)

## How it works

1. **Scraper** (`services/scraper/`) polls the Senate API and House HTML pages every `SCRAPE_INTERVAL_SECONDS` (default 3600s) and queues every video it finds into MongoDB — nothing gets filtered out here.
2. **Downloader** (`services/downloader/`) picks up queued jobs every 30s and pulls audio only (never the full video) into `storage/audio/` — VTT captions straight from CloudFront for captioned Senate videos, FFmpeg extraction for everything else.
3. **Transcriber** (`services/transcriber/`) picks up downloaded jobs every 30s. `should_transcribe()` is the one place that decides if a job is actually worth processing (e.g. too short) — everything else gets transcribed: instantly if a VTT exists, otherwise via Whisper. The MP3 is deleted afterward either way.
4. **Two ways a job can stop without a transcript**: `failed` means a genuine error (network failure, engine crash, missing file) — it's retried up to `JOB_MAX_RETRIES` times (default 3), then left failed and automatically re-queued from scratch next time the scraper rediscovers the video. `excluded` means a deliberate business-rule decision (too short, a live-channel entry with no stable recording) — not an error, not retried, and not re-queued on rediscovery, since the reason won't change. `failed` is the one worth checking; `excluded` is expected. `scripts/list_failed.py` and `scripts/list_excluded.py` show each grouped by reason.
5. **REST API** (`api/`) exposes jobs, transcripts, and per-attempt task logs over HTTP. `GET /health` reports on the pipeline process too, not just the API — each pipeline loop writes a heartbeat to Mongo every cycle, and `/health` reads those, since the API and the pipeline are separate processes that never talk directly. Returns HTTP 503 (not just a JSON field) if any loop's heartbeat has gone stale, so container/orchestrator healthchecks actually catch it.
6. **The pipeline runs under a restart-with-backoff wrapper** (`main.py`'s `run_forever()`) — if something gets past the individual loops' own error handling and crashes the whole process, it restarts automatically instead of staying down.

## Setup

**Requires:** Python 3.12+, [FFmpeg](https://ffmpeg.org/), and MongoDB.

**Windows:**

```powershell
.\install.ps1
```

This installs Python dependencies into a venv, and FFmpeg + MongoDB via `winget` if you don't already have them. Safe to re-run. To do it by hand instead:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# torch from plain pip is CPU-only. If you have an NVIDIA GPU, get a
# CUDA build instead so Whisper actually uses it (check pytorch.org for
# the current CUDA tag - it changes over time, cu130/cu128/cu126 as of 2026):
pip install torch --index-url https://download.pytorch.org/whl/cu130

winget install -e --id Gyan.FFmpeg
winget install -e --id MongoDB.Server
copy .env.example .env
```

**macOS/Linux:**

```bash
./install.sh
```

Same thing, using Homebrew instead of `winget` for FFmpeg/MongoDB. If it's not executable yet (`Permission denied`), run `chmod +x *.sh` once, or just `bash install.sh`.


Note: `install.ps1` (the Windows script) will NOT run in a Mac/Linux shell — it's PowerShell, not bash, and needs `install.sh` instead. By hand instead of the script:

```bash
python3  -m venv venv
source  venv/bin/activate
pip  install -r requirements.txt

pip  install torch      # CPU on Intel Macs/Linux; includes Apple Silicon (MPS) support automatically on M-series Macs


brew  install ffmpeg
brew tap mongodb/brew && brew  install mongodb-community
brew services start mongodb-community
cp .env.example .env
```

| Variable | Description |
|---|---|
| `MONGO_URI` | MongoDB connection string |
| `MONGO_DB_NAME` | Database name |
| `SCRAPE_INTERVAL_SECONDS` | How often the scraper polls the portals (seconds) |
| `JOB_MAX_RETRIES` | Optional, default 3. Retries before giving up on a job / re-queue threshold |
| `HF_HUB_DISABLE_SYMLINKS_WARNING` | Suppresses a HuggingFace warning on Windows (used by faster-whisper) |

Check everything's connected: `venv\Scripts\python.exe -m scripts.db_utils summary` (Windows) or `venv/bin/python3 -m scripts.db_utils summary` (macOS/Linux)

To test setup from scratch, `.\uninstall.ps1` (Windows) or `./uninstall.sh` (macOS/Linux) removes the venv and uninstalls FFmpeg/MongoDB (asks for confirmation first).

## Running

Two separate processes — start both:

```bash
# Windows
run.bat                            # scraper + downloader + transcriber loops
venv\Scripts\uvicorn api.main:app --reload      # REST API

# macOS/Linux
./run.sh                           # scraper + downloader + transcriber loops
venv/bin/uvicorn api.main:app --reload          # REST API
```

### Running with Docker

```bash
cp .env.example .env
docker compose up --build
```

This starts three containers — `mongo`, `pipeline` (the scraper/downloader/transcriber loops), and `api` (on `localhost:8000`) — matching the same three-process split as running it locally, just containerized. The `api` container's healthcheck hits `/health`, which already reports on the `pipeline` container too via Mongo heartbeats, so `docker compose ps` reflects the whole system's health, not just the API's.

The image installs the CPU build of torch, so Whisper runs on CPU in a container by default. For GPU transcription in Docker you'd need an `nvidia/cuda` base image, the NVIDIA Container Toolkit on the host, and a CUDA torch build in the `Dockerfile` instead — not set up here, since it adds a hard dependency on host GPU passthrough that a basic container shouldn't assume.

### Stopping / restarting

**Docker:** `docker compose down` stops everything, `docker compose restart` restarts it, `docker compose up -d` starts it detached in the background. Containers also come back on their own after a crash or host reboot (`restart: unless-stopped` in `docker-compose.yml`).

**Local (no Docker):** `run.bat`/`run.sh` and `uvicorn` (from "Running" above) run in the foreground of whatever terminal started them — closing that terminal or hitting Ctrl+C stops them. For running both in the background instead, with a way to stop/restart them from elsewhere:

```powershell
# Windows
.\start.ps1     # starts pipeline + API in the background, logs to logs\
.\stop.ps1      # stops whatever start.ps1 started
.\restart.ps1   # stop.ps1 then start.ps1
```

```bash
# macOS/Linux
./start.sh      # starts pipeline + API in the background, logs to logs/
./stop.sh       # stops whatever start.sh started
./restart.sh    # stop.sh then start.sh
```

Both write PIDs to `.run/` so `stop`/`restart` know what to stop later. Either is a hard stop (not a graceful shutdown signal), so anything mid-download or mid-transcription gets killed rather than finishing first. That's expected — `claim_jobs()`'s re-claim logic picks those jobs back up automatically next time the pipeline starts, instead of leaving them stuck.

## Where things live

```
main.py                    Entry point — starts the scraper/downloader/transcriber loops under a restart-with-backoff wrapper
run.bat / run.sh           Activates the venv and runs main.py (foreground) — Windows / macOS-Linux
start.ps1 / start.sh       Starts pipeline + API in the background, PIDs tracked in .run/
stop.ps1 / stop.sh         Stops whatever start.* started
restart.ps1 / restart.sh   stop then start
install.ps1 / install.sh   One-time setup: Python deps, FFmpeg, MongoDB
uninstall.ps1 / uninstall.sh   Reverses install.* — removes venv, uninstalls FFmpeg/MongoDB
pytest.ini                 Test config
requirements-dev.txt       Adds pytest on top of requirements.txt
Dockerfile                 One image, shared by the pipeline and api containers (command decides which runs)
docker-compose.yml         mongo + pipeline + api, wired together — see "Running with Docker" above
.dockerignore               Keeps venv/storage/tests out of the image build context

api/                       REST API (FastAPI)
  main.py                    App setup — run with uvicorn, not directly
  routes/                    One file per resource: jobs.py, transcripts.py, tasks.py, health.py

services/                  The three pipeline stages, one folder each
  scraper/
    scraper.py                Orchestrator — runs every detector, queues results into MongoDB
    portal_registry.py        Per-portal settings (expected video count, required fields, retries)
    detectors/                One file per portal: senate_portal.py, house_portal.py
    filter_utils.py, http_utils.py, metadata_utils.py    Shared helpers used by detectors
  downloader/
    downloader.py              Orchestrator — works through queued jobs
    rules.py                   Decides *how* to download a job (which strategy, what filename)
    strategies/                One file per download method: hls.py, http.py, http_audio.py, vtt.py
  transcriber/
    transcriber.py             Orchestrator — has should_transcribe() and the retry loop
    engines/                   whisper.py and vtt_engine.py — the two ways to get text from audio

shared/                    Code every stage depends on
  config.py                  Loads .env, defines JOB_MAX_RETRIES
  logging_config.py           Central logging setup — get_logger(__name__)
  db/database.py              MongoDB connection, claim_jobs() (atomic job claiming), heartbeat()
  db/models/                  One file per collection: job.py, transcript.py, task.py

scripts/                   Manual maintenance — not run automatically
  db_utils.py                 summary / clear / clear-files / reset-failed / fix-audio
  reset_job.py                Reset one job back to pending by URL substring
  list_failed.py               Failed jobs grouped by reason — the ones to actually check
  list_excluded.py             Excluded jobs grouped by reason — expected, not errors
  timing_report.py             Real scrape/download/transcribe timings from job history, by source

tests/                     pytest suite — see "Notes for contributors" below

storage/                   Downloaded audio/captions (gitignored, created at runtime)
```

**Rule of thumb:** each pipeline stage only imports from its own folder or `shared/` — never from another stage's folder. If you're adding a new portal, only `scraper/` changes; a new download method, only `downloader/`; and so on.

## Notes for contributors

- Tests: `pip install -r requirements-dev.txt` then `python -m pytest`. Covers the business-logic-heavy pieces — `should_transcribe()`, VTT parsing, `DownloadRules.build_plan()` (including the live-channel exclusion), portal validation, dedup, and `claim_jobs()`'s concurrency guarantee (via an in-memory fake collection, so it runs without a real MongoDB instance). `tests/conftest.py` stubs `torch`/`faster_whisper` so the suite doesn't need a multi-GB ML install or a GPU just to test pure functions.
- `scripts/db_utils.py` and `scripts/reset_job.py` are manual tools — run them yourself when needed, they're not part of the automated pipeline.
