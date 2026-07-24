"""
Scraper orchestrator.

Runs all registered detectors, validates results against portal business rules,
retries on failure with exponential backoff, and alerts when a portal keeps failing.
"""

import asyncio
from datetime import datetime, timezone

from shared.db.database import jobs_collection
from shared.db.models.job import new_video_job
from services.scraper.detectors.senate_portal import CouncilPortalDetector
from services.scraper.detectors.house_portal import HousePortalDetector
from services.scraper.portal_registry import get_portal_config, validate_videos

# ── Detector registry ─────────────────────────────────────────────────────────
# Add new detectors here alongside their entry in portal_registry.py
DETECTORS = [
    CouncilPortalDetector(),
    HousePortalDetector(),
]


# ── Alert system ─────────────────────────────────────────────────────────────

def _alert(source_name: str, message: str) -> None:
    """
    Send an alert when a portal keeps failing.
    Currently prints to console — replace with email/Slack/webhook later.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"\n{'='*60}")
    print(f"[ALERT] {timestamp}")
    print(f"[ALERT] Portal: {source_name}")
    print(f"[ALERT] {message}")
    print(f"{'='*60}\n")

    # Future: send email, post to Slack, etc.
    # await send_slack_message(f"Portal alert: {source_name} — {message}")
    # await send_email(config.alert_email, subject, body)


# ── Failure tracking ──────────────────────────────────────────────────────────
# Tracks consecutive failures per portal in memory.
# Resets on success. Persists for the life of the process.
_consecutive_failures: dict[str, int] = {}


async def _scrape_with_retry(detector) -> list[dict]:
    """
    Run a detector with retry logic and validation.

    Returns:
        List of validated video dicts, or empty list if all retries failed.
    """
    source = detector.source_name
    config = get_portal_config(source)

    if not config:
        print(f"[scraper] WARNING: No portal config found for '{source}' — skipping validation")
        # Still run the detector, just without validation
        try:
            return await detector.get_new_videos()
        except Exception as e:
            print(f"[scraper] Detector {source} crashed: {e}")
            return []

    last_error = None

    for attempt in range(1, config.max_retries + 1):
        try:
            print(f"[scraper] Scraping {config.display_name} (attempt {attempt}/{config.max_retries})")

            videos = await detector.get_new_videos()

            # Validate results against business rules
            is_valid, reason = validate_videos(videos, config)

            if not is_valid:
                raise ValueError(f"Validation failed: {reason}")

            # Success — reset failure counter
            if source in _consecutive_failures:
                prev = _consecutive_failures.pop(source)
                if prev >= config.alert_after_failures:
                    print(f"[scraper] {config.display_name} recovered after {prev} failures")

            print(f"[scraper] {config.display_name}: {len(videos)} videos found")
            return videos

        except Exception as e:
            last_error = e
            print(f"[scraper] {config.display_name} attempt {attempt} failed: {e}")

            if attempt < config.max_retries:
                delay = config.retry_delay_seconds * attempt  # 30s, 60s, 90s
                print(f"[scraper] Retrying in {delay}s...")
                await asyncio.sleep(delay)

    # All retries exhausted — track failure and possibly alert
    _consecutive_failures[source] = _consecutive_failures.get(source, 0) + 1
    failures = _consecutive_failures[source]

    print(f"[scraper] {config.display_name} failed after {config.max_retries} attempts. "
          f"Consecutive failures: {failures}/{config.alert_after_failures}")

    if failures >= config.alert_after_failures:
        _alert(
            source_name=source,
            message=(
                f"{config.display_name} has failed {failures} times in a row.\n"
                f"Last error: {last_error}\n"
                f"Portal type: {config.portal_type}\n"
                f"Expected at least {config.min_videos_expected} videos."
            )
        )

    return []


# ── Main scrape function ──────────────────────────────────────────────────────

async def run_scrape():
    """
    Run all detectors, validate results, and insert new jobs into MongoDB.
    """
    collection = jobs_collection()

    # Ensure unique index exists — idempotent, cheap if already created
    try:
        await collection.create_index("video_url", unique=True)
    except Exception as e:
        print(f"[scraper] Warning: failed to create index: {e}")

    total_new = 0

    for detector in DETECTORS:
        print(f"\n[scraper] Running detector: {detector.source_name}")

        videos = await _scrape_with_retry(detector)

        if not videos:
            print(f"[scraper] No videos to process for {detector.source_name}")
            continue

        for video in videos:
            url = video["video_url"]
            title = video.get("metadata", {}).get("title", url)

            job = new_video_job(
                video_url=url,
                source=detector.source_name,
                metadata=video.get("metadata", {}),
            )

            try:
                res = await collection.update_one(
                    {"video_url": url},
                    {"$setOnInsert": job},
                    upsert=True,
                )
            except Exception as e:
                print(f"[scraper] Failed to upsert job for {url}: {e}")
                continue

            if getattr(res, "upserted_id", None):
                print(f"[scraper] New job created: {res.upserted_id} — {title}")
                total_new += 1
            else:
                print(f"[scraper] Already seen, skipping: {url}")

    print(f"\n[scraper] Done. {total_new} new job(s) queued.")