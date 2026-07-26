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
# Queries pending jobs, builds a download plan from business rules
# (rules.py), and executes it via strategy implementations (HLS, VTT,
# HTTP audio extract).

import asyncio
import os
from datetime import datetime, timezone

from shared.config import JOB_MAX_RETRIES
from shared.db.database import jobs_collection, claim_jobs
from shared.db.models.job import JobStatus
from services.downloader.config import BATCH_SIZE
from services.downloader.rules import DownloadRules
from services.downloader.strategies.hls import HLSDownloadStrategy
from services.downloader.strategies.http_audio import HTTPAudioExtractStrategy
from services.downloader.strategies.vtt import VTTDownloadStrategy
from shared.logging_config import get_logger

logger = get_logger(__name__)

MAX_RETRIES = JOB_MAX_RETRIES


# Returns the strategy instance for strategy_name; http_audio_extract
# disables SSL verification for known-bad-cert sources (e.g. House).
def _get_strategy(strategy_name: str, job: dict):
    source = job.get("source", "")

    if strategy_name == "hls":
        return HLSDownloadStrategy()
    elif strategy_name == "vtt":
        return VTTDownloadStrategy()
    elif strategy_name == "http_audio_extract":
        verify_ssl = source != "michigan_house"
        return HTTPAudioExtractStrategy(verify_ssl=verify_ssl)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")


# Applies a MongoDB update and stamps updated_at consistently.
async def _update_job(collection, job_id, update: dict):
    await collection.update_one(
        {"_id": job_id},
        {"$set": {**update, "updated_at": datetime.now(timezone.utc)}},
    )


# Runs the download plan for one job and updates its status; skips
# files already on disk so retries are idempotent.
async def _download_job(job: dict, collection) -> None:
    job_id = job["_id"]
    title = job.get("metadata", {}).get("title", str(job_id))
    captioned = job.get("metadata", {}).get("captioned", False)
    retries = job.get("retries", 0)

    logger.info(f"\n[downloader] Starting: {title}")
    logger.info(f"[downloader] Captioned: {captioned}")
    if retries > 0:
        logger.warning(f"[downloader] Retry attempt {retries + 1}/{MAX_RETRIES}")

    plan = DownloadRules.build_plan(job)

    if plan.is_empty():
        if plan.not_ready:
            # Temporary (e.g. not yet transcoded by the source portal) —
            # treated like a normal retryable failure so claim_jobs() picks
            # it back up on its own, instead of EXCLUDED's permanent skip.
            new_retries = retries + 1
            logger.info(f"[downloader] Not ready yet, will retry: {title}")
            await _update_job(collection, job_id, {
                "status": JobStatus.FAILED,
                "failed_stage": "download",
                "error": "Video not yet available from the source portal",
                "retries": new_retries,
            })
            return

        # An empty plan means rules.py deliberately skipped this job
        # (unknown source, or a business rule like the live-channel
        # exclusion) — not a failure, so it's EXCLUDED, not FAILED.
        logger.info(f"[downloader] No download plan for: {title} - excluding")
        await _update_job(collection, job_id, {
            "status": JobStatus.EXCLUDED,
            "failed_stage": "download",
            "error": "No download strategy matched this job (empty plan)",
        })
        return

    # No separate "mark as downloading" update — claim_jobs() already
    # did that atomically in run_downloads() below.
    completed = []
    failed = []

    for item in plan.downloads:
        url = item["url"]
        destination = item["destination"]
        strategy_name = item["strategy"]

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

    if failed:
        new_retries = retries + 1
        logger.warning(f"[downloader] {len(failed)} download(s) failed: {title}")
        if new_retries >= MAX_RETRIES:
            logger.error(f"[downloader] Max retries ({MAX_RETRIES}) reached - giving up: {title}")

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


# Claims pending/retryable jobs atomically and downloads them in
# batches, so a crash mid-download or a second process running
# alongside this one can't both grab the same job.
async def run_downloads() -> None:
    collection = jobs_collection()

    # Also re-claims jobs stuck in DOWNLOADING from a process that died
    # mid-download — otherwise nothing ever moves them out of that status.
    claimed = await claim_jobs(
        collection,
        query={
            "$or": [
                {"status": JobStatus.PENDING},       # Fresh jobs
                {"status": JobStatus.DOWNLOADING},   # Stuck from a prior crash
                {
                    "status": JobStatus.FAILED,       # Retryable failures
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

    logger.info(f"[downloader] {len(pending)} pending, {len(retrying)} retrying - batch size: {BATCH_SIZE}")

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
