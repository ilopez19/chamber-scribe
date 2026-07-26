# MongoDB connection, collection accessors, and the atomic claim_jobs()/
# heartbeat() helpers every pipeline stage depends on.
import asyncio
import uuid
from datetime import datetime, timezone
from pymongo import AsyncMongoClient
from shared.config import MONGO_URI, MONGO_DB_NAME
from shared.logging_config import get_logger

logger = get_logger(__name__)

_client: AsyncMongoClient = None
_client_loop = None


# Returns the shared Mongo client, recreating it if the running event
# loop changed since it was made (a fresh client per loop avoids
# "Task attached to a different loop" errors across pytest runs/restarts).
def get_client() -> AsyncMongoClient:
    global _client, _client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _client is None or _client_loop is not current_loop:
        if _client is not None:
            # close() is a coroutine but this function isn't async, so
            # schedule it on the still-running loop if there is one.
            try:
                running_loop = asyncio.get_running_loop()
                running_loop.create_task(_client.close())
            except RuntimeError:
                pass
        _client = AsyncMongoClient(MONGO_URI)
        _client_loop = current_loop
    return _client


# Returns the app's database from the shared client.
def get_db():
    return get_client()[MONGO_DB_NAME]


# Videos discovered by the scraper, tracked through to a transcript.
def jobs_collection():
    return get_db()["jobs"]


# Finished transcripts (text + segments) produced by the transcriber.
def transcripts_collection():
    return get_db()["transcripts"]


# One record per transcription attempt, for auditing retries/failures.
def tasks_collection():
    return get_db()["tasks"]


# One document per pipeline loop's last heartbeat, read by /health.
def health_collection():
    return get_db()["health"]


# Fails fast at startup if MongoDB isn't reachable, instead of a
# confusing error surfacing later from the first real query.
async def ping():
    await get_client().admin.command("ping")
    logger.info(f"Connected to MongoDB: {MONGO_DB_NAME}")


# Atomically claims every job matching `query`, so two overlapping
# callers (two loop iterations, or two process instances) can never both
# claim the same job — a find()-then-update would leave a race window.
async def claim_jobs(collection, query: dict, claimed_status: str) -> list[dict]:
    claim_id = str(uuid.uuid4())
    await collection.update_many(
        query,
        {"$set": {
            "status": claimed_status,
            "claim_id": claim_id,
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    cursor = collection.find({"claim_id": claim_id})
    return await cursor.to_list(length=None)


# Records that `loop_name` completed a cycle, for /health to read —
# the API reads this from Mongo rather than talking to the pipeline
# process directly, since the two never communicate any other way.
async def heartbeat(loop_name: str, extra: dict | None = None) -> None:
    doc = {"last_seen": datetime.now(timezone.utc)}
    if extra:
        doc.update(extra)
    await health_collection().update_one(
        {"_id": loop_name},
        {"$set": doc},
        upsert=True,
    )
