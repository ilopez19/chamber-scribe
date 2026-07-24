"""Utilities for maintaining the jobs and transcripts collections during
development and operations.

This module contains small one-off maintenance scripts that operate directly
against the MongoDB collections used by the application. It exists to make it
easy to create indexes, wipe or reset records, and run simple audits from the
command line without bringing up the whole service.

Important notes:
- These helpers perform destructive operations (delete/update) and are intended
  for operator use only. Run with care in production.
- The functions use the project's collection helpers from
  ``shared.db.database`` so they run with the same connection configuration as
  the app.
"""

import asyncio
import os
from shared.db.database import jobs_collection, transcripts_collection


async def add_indexes():
    """Create the common MongoDB indexes used by the application.

    This ensures uniqueness for ingest (video_url) and adds common lookup
    indexes used by queries. Creating indexes is idempotent in MongoDB, but
    running this against a large production dataset can be costly — use during
    maintenance windows if possible.

    Side effects:
    - Creates/ensures indexes on the jobs and transcripts collections.
    """
    col = jobs_collection()
    # Ensure each job's source URL is unique to avoid duplicate ingestion.
    await col.create_index("video_url", unique=True)
    # Index status and source because they are used heavily in queries and
    # pipeline filters (improves query performance for status/source queries).
    await col.create_index("status")
    await col.create_index("source")
    # Compound index for queries that filter by both status and source.
    await col.create_index([("status", 1), ("source", 1)])
    print("✅ Unique index created on jobs.video_url")

    trans = transcripts_collection()
    # Create a text index to support full-text search over transcript text.
    await trans.create_index([("text", "text")])
    print("✅ Text search index created on transcripts.text")

async def clear_all():
    """Delete all jobs and transcripts from the database.

    This is a destructive cleanup intended for development or emergency use.
    Side effects:
    - Permanently deletes all documents in the jobs and transcripts
      collections.
    WARNING: Do not run against production unless you intend to remove all
    data.
    """
    jobs = await jobs_collection().delete_many({})
    transcripts = await transcripts_collection().delete_many({})
    print(f"🗑️  Deleted {jobs.deleted_count} jobs")
    print(f"🗑️  Deleted {transcripts.deleted_count} transcripts")


async def reset_failed():
    """Reset jobs with status 'failed' to 'pending' so they are retried.

    This also clears the retry counter and any stored error message to allow
    the job to be processed afresh. Use when transient errors have been
    resolved and it's safe to re-run processing.

    Side effects:
    - Updates multiple job documents in the jobs collection.
    """
    result = await jobs_collection().update_many(
        {"status": "failed"},
        {"$set": {"status": "pending", "retries": 0, "error": None}}
    )
    print(f"♻️  Reset {result.modified_count} failed jobs to pending")


async def reset_status(status: str):
    """Reset all jobs with the given status to 'pending'.

    Args:
        status: The job status value to target (e.g. 'downloaded', 'processing').

    Side effects:
    - Updates matching job documents' status field to 'pending'. This is a
      targeted reset helper used when a particular stage needs to be re-run.
    """
    result = await jobs_collection().update_many(
        {"status": status},
        {"$set": {"status": "pending"}}
    )
    print(f"♻️  Reset {result.modified_count} '{status}' jobs to pending")


async def fix_missing_audio():
    """Find jobs marked 'downloaded' but whose audio file is missing.

    The system stores discovered file paths on the job document; however files
    can be removed by external processes or moved between runs. This helper
    detects jobs that claim to have an MP3 but where the file cannot be found
    on disk and resets them to 'pending' so the downloader will re-fetch.

    Heuristics:
    - Looks for a path ending with '.mp3' in the job's ``file_paths`` list and
      uses ``os.path.exists`` to determine presence.

    Side effects:
    - Updates job documents back to 'pending' when their audio is missing.
    """
    col = jobs_collection()
    cursor = col.find({"status": "downloaded"})
    jobs = await cursor.to_list(length=None)
    fixed = 0
    for job in jobs:
        paths = job.get("file_paths", [])
        # Prefer MP3 files as the canonical downloaded audio artifact.
        audio = next((p for p in paths if p.endswith(".mp3")), None)
        # If there's no recorded MP3 or the file is missing on disk, reset the
        # job to pending so it will be attempted again by the downloader.
        if not audio or not os.path.exists(audio):
            await col.update_one(
                {"_id": job["_id"]},
                {"$set": {"status": "pending"}}
            )
            fixed += 1
    print(f"🔧 Reset {fixed} jobs with missing audio to pending")


async def summary():
    """Print counts of jobs grouped by status and total documents.

    Only non-zero statuses are shown to keep the output concise during daily
    checks. This is a simple operational aid to get a quick view of backlog
    and error counts.

    Side effects: None (read-only).
    """
    col = jobs_collection()
    print("\n📊 Job status summary:")
    # Order statuses to present a logical processing flow to operators.
    for status in ["pending", "downloading", "downloaded", "processing", "transcribed", "failed", "skipped"]:
        count = await col.count_documents({"status": status})
        if count > 0:
            print(f"   {status:<15} {count}")
    total = await col.count_documents({})
    transcript_count = await transcripts_collection().count_documents({})
    print(f"   {'total jobs':<15} {total}")
    print(f"   {'transcripts':<15} {transcript_count}\n")


COMMANDS = {
    "indexes":       (add_indexes,    "Add unique indexes to MongoDB"),
    "clear":         (clear_all,      "Delete all jobs and transcripts"),
    "reset-failed":  (reset_failed,   "Reset failed jobs to pending"),
    "fix-audio":     (fix_missing_audio, "Reset downloaded jobs with missing audio"),
    "summary":       (summary,        "Show job status counts"),
}


async def main(command: str):
    """Dispatch the named command to the corresponding async helper.

    Args:
        command: Key in the COMMANDS mapping.

    Side effects: Executes the selected maintenance function which may modify
    the database.
    """
    if command not in COMMANDS:
        print(f"Unknown command: {command}")
        print(f"Available: {', '.join(COMMANDS.keys())}")
        return
    fn, _ = COMMANDS[command]
    await fn()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.db_utils <command>")
        print("\nCommands:")
        for cmd, (_, desc) in COMMANDS.items():
            print(f"   {cmd:<20} {desc}")
    else:
        asyncio.run(main(sys.argv[1]))