import asyncio
import uuid
from datetime import datetime, timezone
from pymongo import AsyncMongoClient
from shared.config import MONGO_URI, MONGO_DB_NAME
from shared.logging_config import get_logger

logger = get_logger(__name__)

_client: AsyncMongoClient = None
_client_loop = None

#database connection
# awaitable futures and none database blocking prevents bottleneck
def get_client() -> AsyncMongoClient:
    """Return the shared PyMongo Async client, recreating it if the running
    event loop has changed since it was created.

    Uses pymongo's native AsyncMongoClient rather than Motor: Motor is
    deprecated (MongoDB is sunsetting it in favor of async support built
    directly into pymongo) and pymongo's async driver is generally faster
    since it uses asyncio directly instead of a thread pool.

    AsyncMongoClient still can't be shared across event loops (same
    constraint Motor had). Reusing one across a different loop (a fresh loop
    per pytest-asyncio test, or a script calling asyncio.run() more than
    once in the same process) raises RuntimeError: Task attached to a
    different loop. Recreating the client when the loop changes avoids
    that — construction is cheap and doesn't itself open a connection.
    """
    global _client, _client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _client is None or _client_loop is not current_loop:
        if _client is not None:
            # AsyncMongoClient.close() is itself a coroutine (unlike Motor's
            # synchronous close()) — get_client() isn't async, so we can't
            # await it here. Schedule it on the loop that's still running
            # if there is one; otherwise the old client's connections are
            # cleaned up on garbage collection.
            try:
                running_loop = asyncio.get_running_loop()
                running_loop.create_task(_client.close())
            except RuntimeError:
                pass
        _client = AsyncMongoClient(MONGO_URI)
        _client_loop = current_loop
    return _client
# access database table
def get_db():
    return get_client()[MONGO_DB_NAME]

# access to job collection in database
def jobs_collection():
    return get_db()["jobs"]

# access to transcript collection in the database
def transcripts_collection():
    return get_db()["transcripts"]
# access to tasks collection in database
def tasks_collection():
    return get_db()["tasks"]

# access to the health-heartbeat collection — one document per pipeline
# loop (scraper/downloader/transcriber), updated every cycle so the API
# can report whether the pipeline process is actually alive, not just
# whether the API process itself is up.
def health_collection():
    return get_db()["health"]

# sanity check to ensure that the database is connected and working properly
# sent over a TCP, fail fast
async def ping():
    await get_client().admin.command("ping")
    logger.info(f"✅ Connected to MongoDB: {MONGO_DB_NAME}")


async def claim_jobs(collection, query: dict, claimed_status: str) -> list[dict]:
    """Atomically claim every job matching `query` by transitioning it to
    `claimed_status`, tagging each with a unique claim_id in the same
    update.

    This is what makes it safe to invoke a loop's job-pickup step
    concurrently — two overlapping callers (two loop iterations that
    happen to overlap, or a second instance of this process running
    alongside the first) can never both claim the same job. A plain
    find() followed later by a separate update leaves a window open where
    both callers see a job as still eligible before either has marked it
    taken; update_many applies each matched document's update atomically,
    so whichever caller's update reaches a given document first flips its
    status, and the other caller's query simply stops matching it — there
    is no window to race into.

    Returns exactly the documents this call claimed (read back by
    claim_id) in one extra round trip, regardless of how many jobs were
    claimed — not one round trip per job.
    """
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


async def heartbeat(loop_name: str, extra: dict | None = None) -> None:
    """Record that `loop_name` completed a cycle, for /health to read.

    Upserts one document per loop into the health collection. The API
    doesn't talk to this process directly — same as everywhere else in
    this system, it goes through Mongo — so /health can report on the
    pipeline's liveness even though it's a completely separate process
    from the API.
    """
    doc = {"last_seen": datetime.now(timezone.utc)}
    if extra:
        doc.update(extra)
    await health_collection().update_one(
        {"_id": loop_name},
        {"$set": doc},
        upsert=True,
    )