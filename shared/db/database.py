from motor.motor_asyncio import AsyncIOMotorClient
from shared.config import MONGO_URI, MONGO_DB_NAME

_client: AsyncIOMotorClient = None

def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URI)
    return _client

def get_db():
    return get_client()[MONGO_DB_NAME]

def jobs_collection():
    return get_db()["jobs"]

def transcripts_collection():
    return get_db()["transcripts"]

async def ping():
    await get_client().admin.command("ping")
    print(f"✅ Connected to MongoDB: {MONGO_DB_NAME}")