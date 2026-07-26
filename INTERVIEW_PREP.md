# Interview prep — code walkthrough plan

Not part of the app. This is your personal checklist for going through the codebase before the onsite, in the order things actually run (scraper → downloader → transcriber → api), so each stage makes sense before the next depends on it. Delete this file (or leave it — it's harmless) once you're done with it.

For each file: read it, then check you can answer the "be ready for" line without looking. If you can't, that's where to spend more time.

## 0. Start here — the shape of the whole system

- [ ] `design.svg` — the diagram. Trace the grey line top to bottom once, then the blue (storage) and red (health) side-paths.
- [ ] `README.md` — "How it works" (6 numbered points) and "Where things live". This is the 90-second verbal summary if they ask "walk me through your system."
- [ ] `shared/db/models/job.py` — the `JobStatus` enum. Every other file's logic is just moving a job through these 7 states. Read this before anything else; nothing else makes sense without it.
  - **Be ready for:** why `failed` and `excluded` are different statuses, and why only `failed` gets auto-re-queued.

## 1. Config and shared plumbing (small, but everything imports these)

- [ ] `shared/config.py` — env vars, `JOB_MAX_RETRIES`.
- [ ] `shared/logging_config.py` — how `get_logger(__name__)` is set up.
- [ ] `shared/db/database.py` — especially `claim_jobs()` and `heartbeat()`.
  - **Be ready for:** why `claim_jobs()` uses `update_many` + `find` instead of `find_one_and_update` in a loop, and what race condition it closes (two processes both calling `run_downloads()` at once).
- [ ] `shared/db/models/transcript.py`, `shared/db/models/task.py` — quick look, these are simple.

## 2. Stage 1 — Scraper (`services/scraper/`)

- [ ] `services/scraper/detectors/base.py` — `BaseDetector` / `HTTPDetector`. This is the abstraction question — know what it does and does NOT share between portals.
- [ ] `services/scraper/detectors/senate_portal.py` — the JSON API detector. Look at `SENATE_CATALOG_API_BASE_URL`/`CLOUDFRONT_BASE` comments, the tab loop, and the dedup reset at the top of `get_new_videos()`.
  - **Be ready for:** what `SENATE_CATALOG_API_BASE_URL` actually is (AWS API Gateway, catalog ID in the path, not per-video). Why the dedup tracker resets every call.
- [ ] `services/scraper/detectors/house_portal.py` — the HTML-scraping detector. Look at the `item={}` comment.
  - **Be ready for:** why House vs Senate are separate classes, not one. Why House jobs never get `duration_secs`.
- [ ] `services/scraper/filter_utils.py` — `DeduplicationTracker` (used) vs `VideoFilter` (dead code, zero call sites).
  - **Be ready for:** "what keys are in the video dict passed to `filter_by_transcoded`" — and the honest answer that it's unused.
- [ ] `services/scraper/metadata_utils.py` — `normalize_portal_metadata`, `extract_duration`, `extract_size`.
- [ ] `services/scraper/portal_registry.py` — per-portal validation config (expected count, required fields).
- [ ] `services/scraper/scraper.py` — the orchestrator. Read `run_scrape()` and `_scrape_with_retry()` fully.
  - **Be ready for:** why a validation failure alerts but doesn't discard the batch. The re-queue condition (`status == FAILED and retries >= EXHAUSTED_RETRIES`).

## 3. Stage 2 — Downloader (`services/downloader/`)

- [ ] `services/downloader/rules.py` — `DownloadRules.build_plan()`. This is where the live-channel exclusion lives.
  - **Be ready for:** the "Live Stream N" discovery story — what it looked like, how you found the real cause, what changed.
- [ ] `services/downloader/strategies/` — skim all four (`hls.py`, `http.py`, `http_audio.py`, `vtt.py`). Know which portal/format uses which.
- [ ] `services/downloader/downloader.py` — `_download_job()` and `run_downloads()`.
  - **Be ready for:** what happens on an empty plan (excluded, not failed). How `claim_jobs()` is used here specifically.

## 4. Stage 3 — Transcriber (`services/transcriber/`)

- [ ] `services/transcriber/transcriber.py` — `should_transcribe()` first (it's short and it's the one deliberate filter in the whole pipeline), then `_pick_engine()`, then the retry loop in `run_transcriptions()`.
  - **Be ready for:** why VTT-engine failure doesn't consume a retry but Whisper failure does. Why `duration is None` is treated differently from `duration < minimum`.
- [ ] `services/transcriber/engines/vtt_engine.py` — short, the VTT parse path.
- [ ] `services/transcriber/engines/whisper.py` — the CPU-fallback logic.
  - **Be ready for:** the CUDA/cuDNN story — `torch.cuda.is_available()` returning True while faster-whisper's CUDA runtime was still missing, and why that's a different check.

## 5. Stage 4 — API (`api/`)

- [ ] `api/main.py`, `api/routes/jobs.py`, `transcripts.py`, `tasks.py` — quick skim, these are mostly straightforward CRUD-style reads.
- [ ] `api/routes/health.py` — read closely.
  - **Be ready for:** why the API and pipeline never call each other directly, only through Mongo. Why `/health` returns 503 (not just a 200 with `"status": "degraded"` in the body) when a loop's heartbeat is stale.

## 6. Process supervision and concurrency (the "survive" requirement)

- [ ] `main.py` — `scraper_loop()`/`downloader_loop()`/`transcriber_loop()`, then `run_forever()`.
  - **Be ready for:** what happens if the whole process crashes (not just one loop). What resets the backoff timer.
- [ ] Re-read `claim_jobs()` in `shared/db/database.py` one more time here, now that you've seen all three places it's called — this is your answer to "how do you guarantee idempotency" and "how do your services talk to each other."

## 7. Deployment

- [ ] `Dockerfile` — know why torch is installed as a separate `RUN` step, not in `requirements.txt`.
- [ ] `docker-compose.yml` — three services (`mongo`, `pipeline`, `api`), why `MONGO_URI` is overridden per-container instead of read straight from `.env`.
  - **Be ready for:** what you'd change for GPU support in Docker (different base image, NVIDIA Container Toolkit on the host).

## 8. Tests

- [ ] `tests/conftest.py` — how `torch`/`faster_whisper` get stubbed out so tests don't need a GPU or a multi-GB install.
- [ ] Skim the rest of `tests/` — know roughly what's covered (`should_transcribe`, VTT parsing, `build_plan`, `claim_jobs` concurrency via a fake in-memory collection) and, honestly, what isn't (no test hits a real Mongo or a real portal — everything's mocked/faked).

## 9. Known gaps — have honest answers ready, don't get caught flat-footed

- [ ] House portal never populates `duration_secs` (see `house_portal.py` comment) — real HTML limitation, not a bug you missed.
- [ ] No explicit date-range cutoff in the scraper — it polls whatever's on the portal's current tabs.
- [ ] No GPU support in the Docker image (CPU-only torch) — deliberate scope cut, documented in the README.
- [ ] `filter_utils.py`'s `VideoFilter` methods are dead code — if asked, say so plainly rather than pretending they're load-bearing.

## 10. Last pass — run it live once, end to end

- [ ] `docker compose up --build` (or `run.bat` + `uvicorn` locally) and watch a real video go from scraped → downloaded → transcribed in the logs.
- [ ] Hit `GET /health` and `GET /jobs` in a browser or `curl` so you've actually seen real output, not just read the code that produces it.
- [ ] Run `python -m pytest` once yourself so "53 tests, all passing" is something you've personally watched happen, not just a number you were told.
