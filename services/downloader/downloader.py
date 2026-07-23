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


def _get_strategy(strategy_name: str, job: dict):
    """Return the correct strategy instance for a given strategy name."""
    source = job.get("source", "")

    if strategy_name == "hls":
        return HLSDownloadStrategy()
    elif strategy_name == "vtt":
        return VTTDownloadStrategy()
    elif strategy_name == "http_audio":
        verify_ssl = source != "michigan_house"
        return HTTPDownloadStrategy(verify_ssl=verify_ssl)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")


async def _update_job(collection, job_id, update: dict):
    await collection.update_one(
        {"_id": job_id},
        {"$set": {**update, "updated_at": datetime.now(timezone.utc)}},
    )


async def _download_job(job: dict, collection) -> None:
    job_id = job["_id"]
    title = job.get("metadata", {}).get("title", str(job_id))
    captioned = job.get("metadata", {}).get("captioned", False)

    print(f"\n[downloader] Starting: {title}")
    print(f"[downloader] Captioned: {captioned}")

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

        # Skip if already on disk
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
        print(f"[downloader] ❌ {len(failed)} download(s) failed: {title}")
        await _update_job(collection, job_id, {
            "status": JobStatus.FAILED,
            "error": f"Failed downloads: {failed}",
            "retries": job.get("retries", 0) + 1,
        })
    else:
        print(f"[downloader] ✅ All downloads complete: {title}")
        await _update_job(collection, job_id, {
            "status": JobStatus.DOWNLOADED,
            "file_paths": completed,
            "downloaded_at": datetime.now(timezone.utc),
        })


async def run_downloads() -> None:
    collection = jobs_collection()

    # Fetch pending AND failed jobs — retry failures each cycle
    cursor = collection.find({
        "status": {"$in": [JobStatus.PENDING, JobStatus.FAILED]}
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