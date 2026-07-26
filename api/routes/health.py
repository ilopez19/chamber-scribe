# Reports whether the pipeline process (main.py) is actually alive. The
# API and pipeline are separate processes that only talk through Mongo —
# each loop writes a heartbeat every cycle via database.heartbeat(), and
# a heartbeat older than a few times its own interval means that loop is down.

from datetime import datetime, timezone
from fastapi import APIRouter, Response
from shared.db.database import health_collection

router = APIRouter(tags=["health"])

# Grace-period multiplier above a loop's configured interval before it's
# considered stale — e.g. a 30s interval with multiplier 3 tolerates up
# to 90s without a heartbeat before flagging the loop as down.
HEARTBEAT_GRACE_PERIOD_MULTIPLIER = 3
DEFAULT_INTERVAL_SECONDS = 30


# Reports whether the API and each pipeline loop are alive, based on Mongo
# heartbeats; returns HTTP 503 (not just a JSON field) when anything is
# stale, so status-code-only healthchecks (Docker, k8s) still catch it.
# Returns e.g. {"status": "ok", "pipeline_loops": {"scraper_loop": {"healthy": true, ...}}}.
@router.get("/health", summary="Pipeline + API health check")
async def health(response: Response):
    docs = await health_collection().find({}).to_list(length=None)
    now = datetime.now(timezone.utc)

    loops = {}
    # No heartbeats at all means the pipeline has never run (or the health
    # collection was just wiped) — report that plainly rather than as "ok".
    all_healthy = bool(docs)

    for doc in docs:
        interval = doc.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)
        last_seen = doc["last_seen"]
        # pymongo returns naive UTC datetimes even though we stored
        # timezone-aware ones — normalize before subtracting.
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        age_seconds = (now - last_seen).total_seconds()
        healthy = age_seconds < interval * HEARTBEAT_GRACE_PERIOD_MULTIPLIER

        all_healthy = all_healthy and healthy
        loops[doc["_id"]] = {
            "healthy": healthy,
            "last_cycle_ok": doc.get("ok", True),
            "seconds_since_last_heartbeat": round(age_seconds, 1),
        }

    response.status_code = 200 if all_healthy else 503

    return {
        "status": "ok" if all_healthy else "degraded",
        "api": "ok",
        "pipeline_loops": loops,
    }
