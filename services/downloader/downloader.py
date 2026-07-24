import asyncio
import os
from datetime import datetime, timezone

from shared.db.database import jobs_collection
from shared.db.models.job import JobStatus
from services.downloader.config import BATCH_SIZE
from services.downloader.rules import DownloadRules
from services.downloader.strategies.hls import HLSDownloadStrategy
from services.downloader.strategies.http import HTTPDownloadStrategy
from services.downloader.strategies.vtt import VTTDownloadStrategy

"""Downloader service orchestration.

This module queries pending jobs, builds download plans using business
rules, and executes downloads using strategy implementations (HLS, HTTP,
VTT). It includes retry semantics and batching to limit resource usage.
"""

MAX_RETRIES = 3


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

    print(f"\n[downloader] Starting: {title}")
    print(f"[downloader] Captioned: {captioned}")
    if retries > 0:
        print(f"[downloader] Retry attempt {retries + 1}/{MAX_RETRIES}")

    # Build download plan from business rules
    plan = DownloadRules.build_plan(job)

    if plan.is_empty():
        print(f"[downloader] No download plan for: {title} — skipping")
        await _update_job(collection, job_id, {"status": JobStatus.SKIPPED})
        return

    # Mark as downloading
    await _update_job(collection, job_id, {"status": JobStatus.DOWNLOADING})

    completed = []
    failed = []

    for item in plan.downloads:
        url = item["url"]
        destination = item["destination"]
        strategy_name = item["strategy"]

        # Skip if already on disk — supports retrying without re-downloading
        if os.path.exists(destination):
            print(f"[downloader] Already on disk: {destination}")
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
        print(f"[downloader] {len(failed)} download(s) failed: {title}")
        if new_retries >= MAX_RETRIES:
            print(f"[downloader] Max retries ({MAX_RETRIES}) reached — giving up: {title}")

        await _update_job(collection, job_id, {
            "status": JobStatus.FAILED,
            "failed_stage": "download",
            "error": f"Failed downloads: {failed}",
            "retries": new_retries,
        })
    else:
        print(f"[downloader] All downloads complete: {title}")
        await _update_job(collection, job_id, {
            "status": JobStatus.DOWNLOADED,
            "file_paths": completed,
            "downloaded_at": datetime.now(timezone.utc),
            "failed_stage": None,
            "error": None,
        })


async def run_downloads() -> None:
    """Main entry point: fetch pending jobs and run downloads in batches.

    Batching prevents overloading local resources when many jobs queue up.
    Pending jobs are processed before retries to prioritize new work.
    """
    collection = jobs_collection()

    # Fetch pending jobs and failed download jobs under the retry limit
    cursor = collection.find({
        "$or": [
            # Fresh jobs ready to download
            {"status": JobStatus.PENDING},
            # Download failures under the retry limit
            {
                "status": JobStatus.FAILED,
                "failed_stage": "download",
                "retries": {"$lt": MAX_RETRIES},
            },
        ]
    })
    jobs = await cursor.to_list(length=None)

    if not jobs:
        print("[downloader] No pending or failed jobs.")
        return

    pending = [j for j in jobs if j.get("status") == JobStatus.PENDING]
    failed = [j for j in jobs if j.get("status") == JobStatus.FAILED]

    print(f"[downloader] {len(pending)} pending, {len(failed)} retrying — batch size: {BATCH_SIZE}")

    # Process pending first, then retries
    all_jobs = pending + failed
    batches = [
        all_jobs[i: i + BATCH_SIZE]
        for i in range(0, len(all_jobs), BATCH_SIZE)
    ]

    for batch_num, batch in enumerate(batches, start=1):
        print(f"\n[downloader] Batch {batch_num}/{len(batches)}")
        await asyncio.gather(*[
            _download_job(job, collection)
            for job in batch
        ])

    print(f"\n[downloader] All batches complete.")