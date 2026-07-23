import asyncio
from shared.db.database import jobs_collection

CLOUDFRONT_BASE = "https://dlttx48mxf9m3.cloudfront.net/outputs"

async def fix_urls():
    collection = jobs_collection()
    cursor = collection.find({"source": "michigan_senate"})
    jobs = await cursor.to_list(length=None)

    updated = 0
    for job in jobs:
        portal_id = job.get("metadata", {}).get("portal_id")
        if not portal_id:
            continue

        new_url = f"{CLOUDFRONT_BASE}/{portal_id}/Default/HLS/out.m3u8"
        await collection.update_one(
            {"_id": job["_id"]},
            {"$set": {
                "video_url": new_url,
                "status": "pending"
            }}
        )
        updated += 1
        print(f"Fixed: {job.get('metadata', {}).get('title')} → {new_url}")

    print(f"\nDone. Updated {updated} jobs.")

if __name__ == "__main__":
    asyncio.run(fix_urls())