# ═══════════════════════════════════════════════════════════════════════
# PIPELINE STAGE 1 of 3 — SCRAPER
#   Reads:        Senate/House portals (external HTTP, see detectors/)
#   Writes:       MongoDB "jobs" collection, status=pending
#   Triggered by: main.py's scraper_loop(), every SCRAPE_INTERVAL_SECONDS
#   Next stage:   services/downloader/downloader.py
#   Diagram:      design.svg
# ═══════════════════════════════════════════════════════════════════════
# Runs every registered detector and queues every video found — nothing
# gets filtered out here. Validation is a diagnostic-only check; it never
# blocks a video from being queued.

import asyncio
from datetime import datetime, timezone

from shared.config import JOB_MAX_RETRIES
from shared.db.database import jobs_collection
from shared.db.models.job import new_video_job, JobStatus
from services.scraper.detectors.senate_portal import SenatePortalDetector
from services.scraper.detectors.house_portal import HousePortalDetector
from services.scraper.portal_registry import get_portal_config, validate_videos
from shared.logging_config import get_logger

logger = get_logger(__name__)

# Once a failed job hits downloader.py/transcriber.py's shared retry
# ceiling, neither stage will pick it up again — safe to re-queue it here.
EXHAUSTED_RETRIES = JOB_MAX_RETRIES

# ── Detector registry ─────────────────────────────────────────────────────────
# Add new detectors here alongside their entry in portal_registry.py
DETECTORS = [
    SenatePortalDetector(),
    HousePortalDetector(),
]


# ── Alert system ─────────────────────────────────────────────────────────────

# Sends an alert when a portal keeps failing; currently just logs, swap
# in email/Slack/webhook later.
def _alert(source_name: str, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    logger.warning(f"\n{'='*60}")
    logger.warning(f"[ALERT] {timestamp}")
    logger.warning(f"[ALERT] Portal: {source_name}")
    logger.warning(f"[ALERT] {message}")
    logger.warning(f"{'='*60}\n")

    # Future: send email, post to Slack, etc.
    # await send_slack_message(f"Portal alert: {source_name} — {message}")
    # await send_email(config.alert_email, subject, body)


# ── Failure tracking ──────────────────────────────────────────────────────────
# Consecutive failures per portal, in memory; resets on success.
_consecutive_failures: dict[str, int] = {}


# Runs one detector with retries; a validation failure only alerts, it
# never discards videos the detector actually returned.
async def _scrape_with_retry(detector) -> list[dict]:
    source = detector.source_name
    config = get_portal_config(source)

    if not config:
        logger.warning(f"[scraper] WARNING: No portal config found for '{source}' — skipping validation")
        try:
            return await detector.get_new_videos()
        except Exception as e:
            logger.error(f"[scraper] Detector {source} crashed: {e}")
            return []

    last_error = None

    for attempt in range(1, config.max_retries + 1):
        try:
            logger.info(f"[scraper] Scraping {config.display_name} (attempt {attempt}/{config.max_retries})")

            videos = await detector.get_new_videos()

            # A validation failure is a signal to look, not a gate — every
            # video found still gets queued below either way.
            is_valid, reason = validate_videos(videos, config)
            if not is_valid:
                logger.warning(f"[scraper] ⚠️  Validation warning for {config.display_name}: {reason}")
                _alert(
                    source_name=source,
                    message=f"Validation warning (videos still queued as usual): {reason}",
                )

            # Success — reset the failure counter (tracks the scrape itself,
            # independent of the validation outcome above).
            if source in _consecutive_failures:
                prev = _consecutive_failures.pop(source)
                if prev >= config.alert_after_failures:
                    logger.info(f"[scraper] {config.display_name} recovered after {prev} failures")

            logger.info(f"[scraper] {config.display_name}: {len(videos)} videos found")
            return videos

        except Exception as e:
            last_error = e
            logger.warning(f"[scraper] {config.display_name} attempt {attempt} failed: {e}")

            if attempt < config.max_retries:
                delay = config.retry_delay_seconds * attempt  # 30s, 60s, 90s
                logger.warning(f"[scraper] Retrying in {delay}s...")
                await asyncio.sleep(delay)

    # All retries exhausted — track failure and possibly alert
    _consecutive_failures[source] = _consecutive_failures.get(source, 0) + 1
    failures = _consecutive_failures[source]

    logger.error(f"[scraper] {config.display_name} failed after {config.max_retries} attempts. "
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

# Runs every detector, validates results, and inserts new jobs into MongoDB.
async def run_scrape():
    collection = jobs_collection()

    # Ensure unique index exists — idempotent, cheap if already created
    try:
        await collection.create_index("video_url", unique=True)
    except Exception as e:
        logger.warning(f"[scraper] Warning: failed to create index: {e}")

    total_new = 0

    for detector in DETECTORS:
        logger.info(f"\n[scraper] Running detector: {detector.source_name}")

        videos = await _scrape_with_retry(detector)

        if not videos:
            logger.info(f"[scraper] No videos to process for {detector.source_name}")
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
                existing = await collection.find_one(
                    {"video_url": url}, {"status": 1, "retries": 1}
                )

                if existing is None:
                    # Brand new video — insert as normal.
                    res = await collection.insert_one(job)
                    logger.info(f"[scraper] New job created: {res.inserted_id} — {title}")
                    total_new += 1

                elif (
                    existing.get("status") == JobStatus.FAILED
                    and existing.get("retries", 0) >= EXHAUSTED_RETRIES
                ):
                    # Permanently failed and abandoned by the downloader/
                    # transcriber — give it a fresh start instead of leaving
                    # it stuck; file_paths is cleared since that file is gone.
                    await collection.update_one(
                        {"_id": existing["_id"]},
                        {"$set": {
                            "status": JobStatus.PENDING,
                            "retries": 0,
                            "error": None,
                            "failed_stage": None,
                            "file_paths": [],
                            "updated_at": datetime.now(timezone.utc),
                        }}
                    )
                    logger.info(f"[scraper] Re-queuing permanently failed job: {url}")
                    total_new += 1

                else:
                    logger.info(f"[scraper] Already seen, skipping: {url}")

            except Exception as e:
                logger.warning(f"[scraper] Failed to upsert job for {url}: {e}")
                continue

    logger.info(f"\n[scraper] Done. {total_new} new job(s) queued.")
