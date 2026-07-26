# ═══════════════════════════════════════════════════════════════════════
# PIPELINE STAGE 2 of 3 — DOWNLOADER
#   Reads:        MongoDB "jobs" collection, status=pending (or failed,
#                 retrying) — claimed atomically via claim_jobs()
#   Writes:       storage/audio/*.mp3, storage/captions/*.vtt (disk)
#                 MongoDB "jobs" collection, status=downloaded/failed/excluded
#   Triggered by: main.py's downloader_loop(), every 30s
#   Next stage:   services/transcriber/transcriber.py
#   Diagram:      design.svg
# ═══════════════════════════════════════════════════════════════════════
"""Downloader service orchestration.

This module queries pending jobs, builds download plans using business
rules, and executes downloads using strategy implementations (HLS, HTTP,
VTT). It includes retry semantics and batching to limit resource usage.
"""

import asyncio
import os
from datetime import datetime, timezone

from shared.config import JOB_MAX_RETRIES
from shared.db.database import jobs_collection, claim_jobs
from shared.db.models.job import JobStatus
from services.downloader.config import BATCH_SIZE
from services.downloader.rules import DownloadRules
from services.downloader.strategies.hls import HLSDownloadStrategy
from services.downloader.strategies.http import HTTPDownloadStrategy
from services.downloader.strategies.http_audio import HTTPAudioExtractStrategy
from services.downloader.strategies.vtt import VTTDownloadStrategy
from shared.logging_config import get_logger

logger = get_logger(__name__)

MAX_RETRIES = JOB_MAX_RETRIES


def _get_strategy(strategy_name: str, job: dict):
    """Return the correct strategy instance for a given strategy name.

    The HTTP strategy selectively disables SSL verification for known
    problematic sources (e.g. Michigan House) where the remote site has
    certificate issues. This is a pragmatic choice to allow scraping despite
    external infra problems.
    """
    source = job.get("source", "")

    if strategy_name == "hls":
        return HLSDownloadStrategy()
    elif strategy_name == "vtt":
        return VTTDownloadStrategy()
    elif strategy_name == "http_audio":
        # Disables SSL verification only for the specific source with bad certs
        verify_ssl = source != "michigan_house"
        return HTTPDownloadStrategy(verify_ssl=verify_ssl)
    elif strategy_name == "http_audio_extract":
        # Disables SSL verification only for the specific source with bad certs
        verify_ssl = source != "michigan_house"
        return HTTPAudioExtractStrategy(verify_ssl=verify_ssl)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")


async def _update_job(collection, job_id, update: dict):
    """Apply a MongoDB update and stamp updated_at consistently."""
    await collection.update_one(
        {"_id": job_id},
        {"$set": {**update, "updated_at": datetime.now(timezone.utc)}},
    )


async def _download_job(job: dict, collection) -> None:
    """Execute the download plan for a single job and update status.

    Behavior notes:
    - Skips downloads already present on disk to support idempotent retries.
    - Collects completed file paths for storage on the job document.
    """
    job_id = job["_id"]
    title = job.get("metadata", {}).get("title", str(job_id))
    captioned = job.get("metadata", {}).get("captioned", False)
    retries = job.get("retries", 0)

    logger.info(f"\n[downloader] Starting: {title}")
    logger.info(f"[downloader] Captioned: {captioned}")
    if retries > 0:
        logger.warning(f"[downloader] Retry attempt {retries + 1}/{MAX_RETRIES}")

    # Build download plan from business rules
    plan = DownloadRules.build_plan(job)

    if plan.is_empty():
        # An empty plan means DownloadRules deliberately decided not to
        # download this job (unknown source, or a business-rule skip like
        # rules.py's live-channel exclusion) — not a failed attempt, so it
        # gets its own status rather than FAILED. Unlike FAILED, EXCLUDED
        # jobs are never reset to pending by the scraper's re-queue logic,
        # since the reason for excluding them won't change on rediscovery.
        logger.info(f"[downloader] No download plan for: {title} — excluding")
        await _update_job(collection, job_id, {
            "status": JobStatus.EXCLUDED,
            "failed_stage": "download",
            "error": "No download strategy matched this job (empty plan)",
        })
        return

    # No separate "mark as downloading" update here — claim_jobs() already
    # transitioned this job to DOWNLOADING atomically as part of picking
    # it up, in run_downloads() below.
    completed = []
    failed = []

    for item in plan.downloads:
        url = item["url"]
        destination = item["destination"]
        strategy_name = item["strategy"]

        # Skip if already on disk — supports retrying without re-downloading
        if os.path.exists(destination):
            logger.info(f"[downloader] Already on disk: {destination}")
            completed.append(destination)
            continue

        strategy = _get_strategy(strategy_name, job)
        success = await strategy.download(url, destination)

        if success:
            completed.append(destination)
        else:
            failed.append(url)

    # Update job based on results
    if failed:
        new_retries = retries + 1
        logger.warning(f"[downloader] {len(failed)} download(s) failed: {title}")
        if new_retries >= MAX_RETRIES:
            logger.error(f"[downloader] Max retries ({MAX_RETRIES}) reached — giving up: {title}")

        await _update_job(collection, job_id, {
            "status": JobStatus.FAILED,
            "failed_stage": "download",
            "error": f"Failed downloads: {failed}",
            "retries": new_retries,
        })
    else:
        logger.info(f"[downloader] All downloads complete: {title}")
        await _update_job(collection, job_id, {
            "status": JobStatus.DOWNLOADED,
            "file_paths": completed,
            "downloaded_at": datetime.now(timezone.utc),
            "failed_stage": None,
            "error": None,
        })


async def run_downloads() -> None:
    """Main entry point: claim pending/retryable jobs and run downloads in
    batches.

    Batching prevents overloading local resources when many jobs queue up.
    Jobs are claimed atomically (see claim_jobs) before any work starts,
    so this is safe to call even if a previous call is still finishing or
    a second instance of this process is running — neither can end up
    processing the same job as this one.
    """
    collection = jobs_collection()

    # Claiming transitions each matched job straight to DOWNLOADING as
    # part of the same atomic operation that finds it — that's the fix
    # for the race a separate find()-then-update leaves open. retries==0
    # distinguishes a fresh PENDING job from a FAILED-and-retrying one for
    # the log line below, since both now share the same DOWNLOADING status.
    #
    # Also re-claims jobs already sitting in DOWNLOADING: if this process
    # was killed (crash, container restart, `.\stop.ps1`) mid-download,
    # nothing else ever moves that job out of DOWNLOADING, so without this
    # it would stay stuck forever instead of being picked back up under a
    # fresh claim_id next cycle. Mirrors how run_transcriptions() re-claims
    # stuck PROCESSING jobs below.
    claimed = await claim_jobs(
        collection,
        query={
            "$or": [
                # Fresh jobs ready to download
                {"status": JobStatus.PENDING},
                # Stuck from a previous run that died mid-download
                {"status": JobStatus.DOWNLOADING},
                # Download failures under the retry limit
                {
                    "status": JobStatus.FAILED,
                    "failed_stage": "download",
                    "retries": {"$lt": MAX_RETRIES},
                },
            ]
        },
        claimed_status=JobStatus.DOWNLOADING,
    )

    if not claimed:
        logger.info("[downloader] No pending or failed jobs.")
        return

    pending = [j for j in claimed if j.get("retries", 0) == 0]
    retrying = [j for j in claimed if j.get("retries", 0) > 0]

    logger.info(f"[downloader] {len(pending)} pending, {len(retrying)} retrying — batch size: {BATCH_SIZE}")

    # Process pending first, then retries
    all_jobs = pending + retrying
    batches = [
        all_jobs[i: i + BATCH_SIZE]
        for i in range(0, len(all_jobs), BATCH_SIZE)
    ]

    for batch_num, batch in enumerate(batches, start=1):
        logger.info(f"\n[downloader] Batch {batch_num}/{len(batches)}")
        await asyncio.gather(*[
            _download_job(job, collection)
            for job in batch
        ])

    logger.info(f"\n[downloader] All batches complete.")