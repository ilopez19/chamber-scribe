from motor.motor_asyncio import AsyncIOMotorClient
from shared.config import MONGO_URI, MONGO_DB_NAME

_client: AsyncIOMotorClient = None

# awaitable futures and none database blocking
# prevents bottleneck
def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URI)
    return _client

def get_db():
    return get_client()[MONGO_DB_NAME]

# gets tasks from jobs schema
def jobs_collection():
    return get_db()["jobs"]

# gets tasks from transcripts schema
def transcripts_collection():
    return get_db()["transcripts"]

# sanity check to ensure that the database is connected and working properly
# sent over a TCP
async def ping():
    await get_client().admin.command("ping")
    print(f"✅ Connected to MongoDB: {MONGO_DB_NAME}")