import os
from datetime import datetime, timezone
from bson import ObjectId

from shared.db.database import jobs_collection, transcripts_collection
from shared.db.models.job import JobStatus
from shared.db.models.transcript import new_transcript
from services.transcriber.engines.whisper import WhisperEngine

MAX_RETRIES = 3

engine = WhisperEngine()


async def _update_job(collection, job_id: ObjectId, update: dict):
    await collection.update_one(
        {"_id": job_id},
        {"$set": {**update, "updated_at": datetime.now(timezone.utc)}},
    )


async def run_transcriptions() -> None:
    """Pick up all downloaded and retryable failed jobs and transcribe them."""
    jobs_col = jobs_collection()
    transcripts_col = transcripts_collection()

    cursor = jobs_col.find({
        "$or": [
            # Jobs that finished downloading and are ready to transcribe
            {"status": JobStatus.DOWNLOADED},
            # Jobs that failed during transcription specifically, under retry limit
            {
                "status": JobStatus.FAILED,
                "failed_stage": "transcription",
                "retries": {"$lt": MAX_RETRIES},
            },
        ],
        # Never pick up a job that already has a transcript
        "transcript_id": {"$exists": False},
    })
    jobs = await cursor.to_list(length=None)

    if not jobs:
        print("[transcriber] No jobs to transcribe.")
        return

    downloaded = [j for j in jobs if j.get("status") == JobStatus.DOWNLOADED]
    retrying = [j for j in jobs if j.get("status") == JobStatus.FAILED]
    print(f"[transcriber] Found {len(downloaded)} downloaded, {len(retrying)} retrying.")

    for job in jobs:
        job_id = job["_id"]
        title = job.get("metadata", {}).get("title", str(job_id))
        file_paths = job.get("file_paths", [])
        retries = job.get("retries", 0)

        # Find the audio file — prefer .mp3
        audio_path = next(
            (p for p in file_paths if p.endswith(".mp3")),
            None
        )

        if not audio_path or not os.path.exists(audio_path):
            reason = "no audio path in file_paths" if not audio_path else f"file missing: {audio_path}"
            print(f"[transcriber] No audio file for: {title} — {reason}")
            await _update_job(jobs_col, job_id, {
                "status": JobStatus.FAILED,
                "failed_stage": "transcription",
                "error": f"Audio file not found: {reason}",
                "retries": retries + 1,
            })
            continue

        print(f"\n[transcriber] Starting: {title}")
        print(f"[transcriber] Audio: {audio_path}")
        if retries > 0:
            print(f"[transcriber] Retry attempt {retries + 1}/{MAX_RETRIES}")

        await _update_job(jobs_col, job_id, {"status": JobStatus.PROCESSING})

        try:
            result = await engine.transcribe(audio_path)

            # Save transcript to MongoDB
            transcript_doc = new_transcript(
                job_id=str(job_id),
                text=result["text"],
                segments=result["segments"],
            )
            transcript_doc["engine"] = result["engine"]
            transcript_doc["language"] = result["language"]

            insert_result = await transcripts_col.insert_one(transcript_doc)

            print(f"[transcriber] Done: {title}")
            print(f"[transcriber] Segments: {len(result['segments'])}")
            print(f"[transcriber] Transcript ID: {insert_result.inserted_id}")

            await _update_job(jobs_col, job_id, {
                "status": JobStatus.TRANSCRIBED,
                "transcript_id": str(insert_result.inserted_id),
                "transcribed_at": datetime.now(timezone.utc),
                "failed_stage": None,
                "error": None,
            })

            # Clean up audio file after successful transcription
            for path in file_paths:
                if os.path.exists(path) and path.endswith(".mp3"):
                    os.remove(path)
                    print(f"[transcriber] Cleaned up: {path}")

        except Exception as e:
            new_retries = retries + 1
            print(f"[transcriber] Failed: {title} — {e}")
            if new_retries >= MAX_RETRIES:
                print(f"[transcriber] Max retries ({MAX_RETRIES}) reached — giving up: {title}")

            await _update_job(jobs_col, job_id, {
                "status": JobStatus.FAILED,
                "failed_stage": "transcription",
                "error": str(e),
                "retries": new_retries,
            })