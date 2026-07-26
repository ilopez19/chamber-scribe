"""Reports whether the pipeline process (main.py) is actually alive.

The API and the pipeline are two separate processes that never talk to
each other directly — same as everywhere else in this system, this goes
through Mongo instead. Each pipeline loop (scraper/downloader/transcriber)
writes a heartbeat every cycle via shared.db.database.heartbeat(); if a
loop's heartbeat is older than a few times its own interval, that loop
(or the whole process) is down and hasn't recovered yet.
"""

from datetime import datetime, timezone
from fastapi import APIRouter
from shared.db.database import health_collection

router = APIRouter(tags=["health"])

# How much longer than a loop's own interval to allow before calling it
# stale. Loops don't run instantly and Mongo writes have some latency, so
# a small multiplier avoids false alarms right at the interval boundary.
STALE_MULTIPLIER = 3
DEFAULT_INTERVAL_SECONDS = 30


@router.get("/health")
async def health():
    docs = await health_collection().find({}).to_list(length=None)
    now = datetime.now(timezone.utc)

    loops = {}
    # No heartbeats at all means the pipeline has never run (or the health
    # collection was just wiped) — report that plainly rather than as "ok".
    all_healthy = bool(docs)

    for doc in docs:
        interval = doc.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)
        last_seen = doc["last_seen"]
        # pymongo returns naive UTC datetimes by default even though we
        # stored timezone-aware ones — normalize before subtracting.
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        age_seconds = (now - last_seen).total_seconds()
        healthy = age_seconds < interval * STALE_MULTIPLIER

        all_healthy = all_healthy and healthy
        loops[doc["_id"]] = {
            "healthy": healthy,
            "last_cycle_ok": doc.get("ok", True),
            "seconds_since_last_heartbeat": round(age_seconds, 1),
        }

    return {
        "status": "ok" if all_healthy else "degraded",
        "api": "ok",
        "pipeline_loops": loops,
    }
