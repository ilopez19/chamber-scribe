import os
from datetime import datetime, timezone
from bson import ObjectId

from shared.db.database import jobs_collection, transcripts_collection
from shared.db.models.job import JobStatus
from shared.db.models.transcript import new_transcript
from services.transcriber.engines.whisper import WhisperEngine
from services.transcriber.engines.vtt_engine import VTTEngine

"""Transcription orchestration.

This module picks the appropriate transcription engine (VTT fast-path or
Whisper), runs transcriptions for jobs that are ready or retryable, and
persists transcript documents. It contains retry and fallback logic to
improve resilience when caption parsing fails.

Notes:
- VTT parsing is preferred for captioned Senate videos because it is fast
  and deterministic. Whisper is the fallback for audio-based transcription.
"""

MAX_RETRIES = 3

whisper_engine = WhisperEngine()
vtt_engine = VTTEngine()


def _pick_engine(job: dict, audio_path: str):
    """Choose VTTEngine when captions are present on disk, otherwise Whisper.

    The decision prefers VTT when the job metadata says captioned=True and a
    .vtt file exists at the expected derived path. If the VTT is missing we
    fall back to Whisper to avoid silently dropping work.
    """
    captioned = job.get("metadata", {}).get("captioned", False)

    if captioned:
        expected_vtt = vtt_engine._expected_vtt_path(audio_path)
        if os.path.exists(expected_vtt):
            print(f"[transcriber] Using VTT fast path: {expected_vtt}")
            return vtt_engine, "vtt"
        # NOTE: If the metadata claims captions exist but the file is missing
        # we prefer to fall back to Whisper rather than failing the job
        # immediately; this guards against transient file/move issues.
        print(f"[transcriber] Captioned=True but no VTT found at {expected_vtt} — falling back to Whisper")

    return whisper_engine, "whisper"


def _is_vtt_job(job: dict) -> bool:
    """Return True when the job already contains a VTT in file_paths.

    Used to prioritize VTT jobs so they are processed quickly (they are fast
    to transcribe) and free up resources.
    """
    file_paths = job.get("file_paths", [])
    return any(p.endswith(".vtt") for p in file_paths)


async def _update_job(collection, job_id: ObjectId, update: dict):
    """Update a job document and stamp the updated_at time.

    Centralizing the timestamp update ensures consistent audit fields on
    every job modification.
    """
    await collection.update_one(
        {"_id": job_id},
        {"$set": {**update, "updated_at": datetime.now(timezone.utc)}},
    )


async def run_transcriptions() -> None:
    """Find ready jobs and produce transcript documents.

    Behavior:
    - Picks jobs that are downloaded, processing, or failed during transcription
      with retries left.
    - Prioritizes VTT-based jobs so fast-path transcriptions complete quickly.
    - On failure, attempts a Whisper fallback when VTT parsing fails.
    - Cleans up MP3 files after successful transcription to save disk space.
    """
    jobs_col = jobs_collection()
    transcripts_col = transcripts_collection()

    cursor = jobs_col.find({
        "$or": [
            {"status": JobStatus.DOWNLOADED},
            {"status": JobStatus.PROCESSING},
            {
                "status": JobStatus.FAILED,
                "failed_stage": "transcription",
                "retries": {"$lt": MAX_RETRIES},
            },
        ],
        "transcript_id": {"$exists": False},
    })
    jobs = await cursor.to_list(length=None)

    if not jobs:
        print("[transcriber] No jobs to transcribe.")
        return

    # Process VTT jobs first because they are fast and unblock downstream
    # work quickly.
    jobs = sorted(jobs, key=lambda j: (0 if _is_vtt_job(j) else 1))

    downloaded = [j for j in jobs if j.get("status") == JobStatus.DOWNLOADED]
    processing = [j for j in jobs if j.get("status") == JobStatus.PROCESSING]
    retrying = [j for j in jobs if j.get("status") == JobStatus.FAILED]
    print(f"[transcriber] Found {len(downloaded)} downloaded, {len(processing)} stuck, {len(retrying)} retrying.")

    for job in jobs:
        job_id = job["_id"]
        title = job.get("metadata", {}).get("title", str(job_id))
        file_paths = job.get("file_paths", [])
        retries = job.get("retries", 0)
        captioned = job.get("metadata", {}).get("captioned", False)

        audio_path = next((p for p in file_paths if p.endswith(".mp3")), None)
        vtt_path = next((p for p in file_paths if p.endswith(".vtt")), None)

        if not audio_path and not vtt_path:
            # Nothing to transcribe; mark as failed to draw operator attention.
            print(f"[transcriber] No audio or VTT file for: {title} — skipping")
            await _update_job(jobs_col, job_id, {
                "status": JobStatus.FAILED,
                "failed_stage": "transcription",
                "error": "No audio or VTT file found in file_paths",
                "retries": retries + 1,
            })
            continue

        # If only a VTT exists, treat it as the transcription input
        if not audio_path and vtt_path:
            audio_path = vtt_path

        print(f"\n[transcriber] Starting: {title}")
        print(f"[transcriber] Captioned: {captioned}")
        if retries > 0:
            print(f"[transcriber] Retry attempt {retries + 1}/{MAX_RETRIES}")

        await _update_job(jobs_col, job_id, {"status": JobStatus.PROCESSING})

        engine, engine_name = _pick_engine(job, audio_path)

        try:
            result = await engine.transcribe(audio_path)

            transcript_doc = new_transcript(
                job_id=str(job_id),
                text=result["text"],
                segments=result["segments"],
            )
            transcript_doc["engine"] = result["engine"]
            transcript_doc["language"] = result["language"]

            insert_result = await transcripts_col.insert_one(transcript_doc)

            print(f"[transcriber] Done: {title}")
            print(f"[transcriber] Engine: {result['engine']}")
            print(f"[transcriber] Segments: {len(result['segments'])}")
            print(f"[transcriber] Transcript ID: {insert_result.inserted_id}")

            await _update_job(jobs_col, job_id, {
                "status": JobStatus.TRANSCRIBED,
                "transcript_id": str(insert_result.inserted_id),
                "transcribed_at": datetime.now(timezone.utc),
                "transcription_engine": result["engine"],
                "failed_stage": None,
                "error": None,
            })

            # Remove MP3 files to conserve disk; keep VTTs for auditing.
            for path in file_paths:
                if os.path.exists(path) and path.endswith(".mp3"):
                    os.remove(path)
                    print(f"[transcriber] Cleaned up: {path}")

        except Exception as e:
            # If VTT parsing failed, attempt an audio-based Whisper fallback.
            if engine_name == "vtt":
                print(f"[transcriber] VTT failed ({e}) — falling back to Whisper")
                try:
                    result = await whisper_engine.transcribe(audio_path)

                    transcript_doc = new_transcript(
                        job_id=str(job_id),
                        text=result["text"],
                        segments=result["segments"],
                    )
                    transcript_doc["engine"] = result["engine"]
                    transcript_doc["language"] = result["language"]

                    insert_result = await transcripts_col.insert_one(transcript_doc)

                    print(f"[transcriber] Done (Whisper fallback): {title}")

                    await _update_job(jobs_col, job_id, {
                        "status": JobStatus.TRANSCRIBED,
                        "transcript_id": str(insert_result.inserted_id),
                        "transcribed_at": datetime.now(timezone.utc),
                        "transcription_engine": result["engine"],
                        "failed_stage": None,
                        "error": None,
                    })

                    for path in file_paths:
                        if os.path.exists(path) and path.endswith(".mp3"):
                            os.remove(path)

                    continue

                except Exception as whisper_error:
                    e = whisper_error

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