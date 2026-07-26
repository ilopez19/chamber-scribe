"""One-off helper: reset job(s) back to 'pending' by matching part of their
video_url (e.g. a filename fragment or portal_id). Useful for retesting a
single video after a downloader/transcriber fix without resetting the whole
batch via db_utils.reset_status.

Usage:
    python -m scripts.reset_job <video_url substring>

Example:
    python -m scripts.reset_job AGRR-022526
"""

import asyncio
import sys

from shared.db.database import jobs_collection


async def reset_job(match: str) -> None:
    """Reset every job whose video_url contains `match` back to pending.

    Clears retries and any stored error so the job is treated as fresh by
    both the downloader and transcriber loops.
    """
    col = jobs_collection()
    result = await col.update_many(
        {"video_url": {"$regex": match}},
        {"$set": {"status": "pending", "retries": 0, "error": None}},
    )
    print(f"Matched + reset {result.modified_count} job(s) containing '{match}' to pending")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.reset_job <video_url substring>")
    else:
        asyncio.run(reset_job(sys.argv[1]))
