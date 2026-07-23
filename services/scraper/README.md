# Scraper utilities

This folder contains shared utilities and detector implementations used by the scraper subsystem.

Purpose
- Remove duplicated logic across detectors and centralize common behaviour (HTTP client, retry/backoff, filtering, deduplication, metadata normalization).
- Make detectors easier to write, test and maintain by providing small, well-named building blocks.

Files and responsibilities
- `config.py` — HTTP configuration constants (HTTP_TIMEOUT, HTTP_VERIFY, MAX_RETRIES, RETRY_DELAY).
- `http_utils.py` — Shared HTTP helpers:
  - `HTTPClient.create_client(...)` — create a consistently configured `httpx.AsyncClient`.
  - `fetch_with_retry(client, url, ...)` — performs GET with retry + exponential backoff and raises on final failure.
- `filter_utils.py` — Filtering and deduplication helpers:
  - `VideoFilter` — static methods for common checks (transcoded, access level, duration, general validity).
  - `DeduplicationTracker` — an in-memory tracker to mark and filter seen IDs within a detector run.
- `metadata_utils.py` — Metadata extraction & normalization:
  - `MetadataExtractor.normalize_portal_metadata(...)` — normalize and enrich portal metadata (duration_secs, duration_mins, size_bytes, size_mb, portal, title, portal_id, ...).
  - `MetadataExtractor.build_video_record(video_url, metadata)` — build the dict format expected by the scraper/job creator.
- `detectors/base.py` — Detector base classes:
  - `BaseDetector` — abstract interface (requires `source_name` and `async get_new_videos()`).
  - `HTTPDetector` — optional base for HTTP-backed detectors that manages a shared `httpx.AsyncClient`.
- `detectors/house_portal.py` and `detectors/senate_portal.py` — concrete detectors refactored to use the shared utilities.

Why these changes
- Remove duplicated HTTP/retry logic across detectors and centralize consistent behaviour.
- Provide a single place to change retry/backoff/timeout settings via `config.py`.
- Centralize common filters and deduplication so tests and fixes happen in one place (`filter_utils.py`).
- Normalize metadata across detectors so downstream job creation sees consistent fields (`metadata_utils.py`).

Quick reference — how to use the utilities

HTTP
- Use `HTTPDetector.get_client()` to obtain an async `httpx.AsyncClient` configured consistently.
- Use `fetch_with_retry(client, url, ...)` for network requests that should retry on failure.

Example (inside a detector — use inside an async coroutine):
```python
# inside an async method or coroutine
async def fetch_example(self):
    client = await self.get_client()
    response = await fetch_with_retry(client, "https://example.com/path")
    data = response.json()
```

Filtering & dedupe
- Use `VideoFilter` static methods to apply standard rules (transcoded/access/duration).
- Use a `DeduplicationTracker` instance inside a detector to avoid returning duplicate items within a single run.

Example:
```python
dedup = DeduplicationTracker()
items = dedup.get_unseen_videos(raw_items, id_key="_id")
for item in items:
    if not VideoFilter.filter_by_transcoding(item):
        continue
        *** End Patch
