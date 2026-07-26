# ═══════════════════════════════════════════════════════════════════════
# PIPELINE STAGE 3 of 3 — TRANSCRIBER
#   Reads:        MongoDB "jobs" collection, status=downloaded (or
#                 processing/failed, retrying) — claimed atomically via
#                 claim_jobs(); storage/audio or storage/captions from disk
#   Writes:       MongoDB "transcripts" + "tasks" collections
#                 MongoDB "jobs" collection, status=transcribed/failed/excluded
#   Triggered by: main.py's transcriber_loop(), every 30s
#   Next stage:   api/ (serves the finished transcript over REST)
#   Diagram:      design.svg
# ═══════════════════════════════════════════════════════════════════════
# Picks the right engine (VTT fast path or Whisper), runs transcription for
# ready/retryable jobs, and persists transcript documents.
# should_transcribe() below is the pipeline's one business-logic checkpoint —
# the scraper and downloader don't filter anything, so "is this worth
# processing" lives in a single place instead of being spread across them.

import asyncio
import os
from datetime import datetime, timezone
from bson import ObjectId

from shared.config import JOB_MAX_RETRIES
from shared.db.database import jobs_collection, transcripts_collection, tasks_collection, claim_jobs
from shared.db.models.job import JobStatus
from shared.db.models.transcript import new_transcript
from shared.db.models.task import new_task
from services.transcriber.config import MIN_DURATION_SECONDS, TRANSCRIBE_TIMEOUT_SECONDS
from services.transcriber.engines.whisper import WhisperEngine
from services.transcriber.engines.vtt_engine import VTTEngine
from shared.logging_config import get_logger

logger = get_logger(__name__)

MAX_RETRIES = JOB_MAX_RETRIES
RETRY_DELAY_SECONDS = 5  # base delay before retrying a failed transcription; doubles each attempt

whisper_engine = WhisperEngine()
vtt_engine = VTTEngine()


# Decides whether a downloaded job is worth transcribing; returns
# (should_transcribe, reason), reason empty when True.
def should_transcribe(job: dict) -> tuple[bool, str]:
    duration = job.get("metadata", {}).get("duration_secs")

    # Only reject on duration when it's actually known — House jobs report
    # None, not 0, and treating that as "too short" would skip every House video.
    if duration is not None and duration < MIN_DURATION_SECONDS:
        return False, f"Duration {duration}s is below the {MIN_DURATION_SECONDS}s minimum"

    return True, ""


# Picks VTTEngine when a caption file exists, otherwise Whisper.
def _pick_engine(job: dict, vtt_path: str | None):
    captioned = job.get("metadata", {}).get("captioned", False)

    if captioned:
        if vtt_path and os.path.exists(vtt_path):
            logger.info(f"[transcriber] Using VTT fast path: {vtt_path}")
            return vtt_engine, "vtt"
        # Metadata claims captions but the file is missing — fall back to
        # Whisper rather than failing outright; guards against transient issues.
        logger.warning(f"[transcriber] Captioned=True but no VTT found (vtt_path={vtt_path}) — falling back to Whisper")

    return whisper_engine, "whisper"


# True when the job already has a VTT in file_paths, used to prioritize
# fast VTT jobs ahead of slower Whisper ones.
def _is_vtt_job(job: dict) -> bool:
    file_paths = job.get("file_paths", [])
    return any(p.endswith(".vtt") for p in file_paths)


# Applies a MongoDB update and stamps updated_at consistently.
async def _update_job(collection, job_id: ObjectId, update: dict):
    await collection.update_one(
        {"_id": job_id},
        {"$set": {**update, "updated_at": datetime.now(timezone.utc)}},
    )


# Claims ready/retryable jobs, transcribes them (VTT-first), and persists
# transcript documents; falls back to Whisper if VTT parsing fails.
async def run_transcriptions() -> None:
    jobs_col = jobs_collection()
    transcripts_col = transcripts_collection()

    # Claiming transitions every matched job to PROCESSING atomically,
    # closing the race a separate find()-then-update would leave open
    # between overlapping calls or process instances; a job already stuck
    # in PROCESSING (e.g. a prior crash mid-transcription) gets re-claimed too.
    jobs = await claim_jobs(
        jobs_col,
        query={
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
        },
        claimed_status=JobStatus.PROCESSING,
    )

    if not jobs:
        logger.info("[transcriber] No jobs to transcribe.")
        return

    # Process VTT jobs first — they're fast and unblock downstream work quickly.
    jobs = sorted(jobs, key=lambda j: (0 if _is_vtt_job(j) else 1))

    downloaded = [j for j in jobs if j.get("retries", 0) == 0]
    retrying = [j for j in jobs if j.get("retries", 0) > 0]
    logger.info(f"[transcriber] Found {len(downloaded)} downloaded/fresh, {len(retrying)} retrying.")

    for job in jobs:
        job_id = job["_id"]
        title = job.get("metadata", {}).get("title", str(job_id))
        file_paths = job.get("file_paths", [])
        retries = job.get("retries", 0)
        captioned = job.get("metadata", {}).get("captioned", False)

        audio_path = next((p for p in file_paths if p.endswith(".mp3")), None)
        vtt_path = next((p for p in file_paths if p.endswith(".vtt")), None)

        if not audio_path and not vtt_path:
            # A job reaching transcription with no recorded file is unexpected
            # (the downloader shouldn't mark anything DOWNLOADED without one).
            logger.warning(f"[transcriber] No audio or VTT file for: {title} — marking failed")
            await _update_job(jobs_col, job_id, {
                "status": JobStatus.FAILED,
                "failed_stage": "transcription",
                "error": "No audio or VTT file found in file_paths",
                "retries": retries + 1,
            })
            continue

        if not audio_path and vtt_path:
            audio_path = vtt_path

        worth_it, skip_reason = should_transcribe(job)
        if not worth_it:
            # A business decision (e.g. too short), not a failure — EXCLUDED
            # so the scraper's re-queue logic (which only resets FAILED) leaves it alone.
            logger.info(f"[transcriber] Excluding (not worth transcribing): {title} — {skip_reason}")
            await _update_job(jobs_col, job_id, {
                "status": JobStatus.EXCLUDED,
                "failed_stage": "transcription",
                "error": skip_reason,
            })
            for path in file_paths:
                if os.path.exists(path) and path.endswith(".mp3"):
                    os.remove(path)
                    logger.info(f"[transcriber] Cleaned up (skipped): {path}")
            continue

        logger.info(f"\n[transcriber] Starting: {title}")
        logger.info(f"[transcriber] Captioned: {captioned}")

        # No separate "mark as processing" update — claim_jobs() already did that above.
        engine, engine_name = _pick_engine(job, vtt_path)
        done = False

        # Retries transcription in place up to MAX_RETRIES instead of waiting
        # for a later run_transcriptions() call to pick it back up. A VTT
        # failure falls back to Whisper without consuming a retry — only
        # repeated Whisper failures count against the retry budget.
        while retries < MAX_RETRIES and not done:
            if retries > 0:
                logger.warning(f"[transcriber] Retry attempt {retries + 1}/{MAX_RETRIES}")

            # A fresh task record per attempt makes each attempt auditable,
            # including the VTT-to-Whisper fallback.
            task_doc = new_task(
                job_id=str(job_id),
                task_type="transcription",
                metadata={
                    "captioned": captioned,
                    "audio_path": audio_path,
                    "vtt_path": vtt_path,
                    "file_paths": file_paths,
                }
            )
            task_insert = await tasks_collection().insert_one(task_doc)
            task_id = task_insert.inserted_id

            await tasks_collection().update_one(
                {"_id": task_id},
                {"$set": {"status": "processing", "started_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
            )

            try:
                # Bounded the same way hls.py bounds ffmpeg: a stuck decode
                # would otherwise block this loop and its heartbeat forever.
                # This only cancels the await, not the underlying thread-pool
                # work — an abandoned Whisper attempt keeps running in the
                # background, but the loop itself is freed up immediately.
                result = await asyncio.wait_for(
                    engine.transcribe(audio_path), timeout=TRANSCRIBE_TIMEOUT_SECONDS
                )

                transcript_doc = new_transcript(
                    job_id=str(job_id),
                    text=result["text"],
                    segments=result["segments"],
                )
                transcript_doc["engine"] = result["engine"]
                transcript_doc["language"] = result["language"]

                insert_result = await transcripts_col.insert_one(transcript_doc)

                await tasks_collection().update_one(
                    {"_id": task_id},
                    {"$set": {
                        "status": "done",
                        "result_id": str(insert_result.inserted_id),
                        "finished_at": datetime.now(timezone.utc),
                        "metadata": {
                            "captioned": captioned,
                            "audio_path": audio_path,
                            "vtt_path": vtt_path,
                            "file_paths": file_paths,
                            "engine": result["engine"],
                            "language": result["language"],
                        },
                        "updated_at": datetime.now(timezone.utc),
                    }}
                )

                logger.info(f"[transcriber] Done: {title}")
                logger.info(f"[transcriber] Engine: {result['engine']}")
                logger.info(f"[transcriber] Segments: {len(result['segments'])}")
                logger.info(f"[transcriber] Transcript ID: {insert_result.inserted_id}")

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
                        logger.info(f"[transcriber] Cleaned up: {path}")

                done = True

            except Exception as e:
                try:
                    await tasks_collection().update_one(
                        {"_id": task_id},
                        {"$set": {
                            "status": "failed",
                            "error": str(e),
                            "finished_at": datetime.now(timezone.utc),
                            "updated_at": datetime.now(timezone.utc),
                        }}
                    )
                except Exception:
                    pass  # Don't mask the original error if the task update fails

                if engine_name == "vtt":
                    # A one-time engine switch, not a retry — doesn't consume
                    # the retry budget; loop immediately re-attempts with Whisper.
                    logger.warning(f"[transcriber] VTT failed ({e}) — falling back to Whisper")
                    engine, engine_name = whisper_engine, "whisper"
                    await _update_job(jobs_col, job_id, {
                        "status": JobStatus.PROCESSING,
                        "failed_stage": "transcription",
                        "error": str(e),
                    })
                    continue

                retries += 1
                logger.warning(f"[transcriber] Failed ({retries}/{MAX_RETRIES}): {title} — {e}")
                await _update_job(jobs_col, job_id, {
                    "status": JobStatus.FAILED,
                    "failed_stage": "transcription",
                    "error": str(e),
                    "retries": retries,
                })

                if retries >= MAX_RETRIES:
                    logger.error(f"[transcriber] Max retries ({MAX_RETRIES}) reached — giving up: {title}")
                    # Clean up the audio file so a permanently-failed job
                    # doesn't hold onto disk space forever.
                    for path in file_paths:
                        if os.path.exists(path) and path.endswith(".mp3"):
                            os.remove(path)
                            logger.info(f"[transcriber] Cleaned up (gave up): {path}")
                else:
                    # Doubles each retry (5s, 10s, ...) instead of hammering
                    # the same failure immediately; sleep yields control so
                    # the other loops keep running.
                    delay = RETRY_DELAY_SECONDS * (2 ** (retries - 1))
                    logger.warning(f"[transcriber] Waiting {delay}s before retry...")
                    await asyncio.sleep(delay)
