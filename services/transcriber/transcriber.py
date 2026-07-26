import asyncio
import os
from datetime import datetime, timezone
from bson import ObjectId

from shared.config import JOB_MAX_RETRIES
from shared.db.database import jobs_collection, transcripts_collection, tasks_collection, claim_jobs
from shared.db.models.job import JobStatus
from shared.db.models.transcript import new_transcript
from shared.db.models.task import new_task
from services.transcriber.config import MIN_DURATION_SECONDS
from services.transcriber.engines.whisper import WhisperEngine
from services.transcriber.engines.vtt_engine import VTTEngine
from shared.logging_config import get_logger

logger = get_logger(__name__)

"""Transcription orchestration.

This module picks the appropriate transcription engine (VTT fast-path or
Whisper), runs transcriptions for jobs that are ready or retryable, and
persists transcript documents. It contains retry and fallback logic to
improve resilience when caption parsing fails.

Notes:
- VTT parsing is preferred for captioned Senate videos because it is fast
  and deterministic. Whisper is the fallback for audio-based transcription.
- By design, the scraper and downloader don't filter anything — every
  discovered video gets recorded and downloaded. should_transcribe() below
  is the one deliberate business-logic checkpoint in the pipeline, so "is
  this worth processing" lives in a single place instead of being spread
  across detectors and download rules.
"""

MAX_RETRIES = JOB_MAX_RETRIES
RETRY_DELAY_SECONDS = 5  # base delay before retrying a failed transcription; doubles each attempt

whisper_engine = WhisperEngine()
vtt_engine = VTTEngine()


def should_transcribe(job: dict) -> tuple[bool, str]:
    """Decide whether a downloaded job is actually worth transcribing.

    This is the single gatekeeping point for the whole pipeline. Add
    further business rules here as they come up, rather than back in the
    scraper/downloader.

    Returns:
        (should_transcribe, reason) — reason is empty string when True.
    """
    duration = job.get("metadata", {}).get("duration_secs")

    # Only reject on duration when it's actually known. House jobs don't
    # currently report duration_secs at all (None, not 0) — treating
    # "unknown" the same as "too short" would silently skip every House
    # video, which isn't the intent.
    if duration is not None and duration < MIN_DURATION_SECONDS:
        return False, f"Duration {duration}s is below the {MIN_DURATION_SECONDS}s minimum"

    return True, ""


def _pick_engine(job: dict, vtt_path: str | None):
    """Choose VTTEngine when a caption file is present, otherwise Whisper.

    vtt_path comes straight from the job's file_paths (set by the
    downloader), not derived/guessed from a filename pattern — captioned
    Senate jobs only ever download a .vtt, never an .mp3, so there's no
    audio path to derive anything from in the first place.
    """
    captioned = job.get("metadata", {}).get("captioned", False)

    if captioned:
        if vtt_path and os.path.exists(vtt_path):
            logger.info(f"[transcriber] Using VTT fast path: {vtt_path}")
            return vtt_engine, "vtt"
        # NOTE: If the metadata claims captions exist but the file is missing
        # we prefer to fall back to Whisper rather than failing the job
        # immediately; this guards against transient file/move issues.
        logger.warning(f"[transcriber] Captioned=True but no VTT found (vtt_path={vtt_path}) — falling back to Whisper")

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

    # Claiming transitions every matched job straight to PROCESSING as
    # part of the same atomic operation that finds it (see claim_jobs in
    # shared/db/database.py) — that closes the race a separate
    # find()-then-update leaves open between two overlapping calls to
    # this function, or two instances of this process. A job already
    # stuck in PROCESSING (e.g. this process crashed mid-transcription
    # last time) matches too and gets re-claimed under a fresh claim_id,
    # which is how those get picked back up instead of staying stuck.
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

    # Process VTT jobs first because they are fast and unblock downstream
    # work quickly.
    jobs = sorted(jobs, key=lambda j: (0 if _is_vtt_job(j) else 1))

    # retries > 0 means this had already failed at least once before being
    # claimed just now; can't tell PROCESSING-before-claim apart from
    # DOWNLOADED-before-claim anymore since claiming overwrote status on
    # both, but that distinction isn't actionable here, just informational.
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
            # Nothing to transcribe; mark as failed to draw operator attention.
            # A job reaching transcription with neither file recorded is
            # unexpected (the downloader shouldn't mark anything DOWNLOADED
            # without one) — worth a WARNING, not routine INFO noise.
            logger.warning(f"[transcriber] No audio or VTT file for: {title} — marking failed")
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

        # Single business-logic checkpoint: everything gets downloaded, but
        # not everything is worth spending Whisper/VTT time on.
        worth_it, skip_reason = should_transcribe(job)
        if not worth_it:
            # A business decision (e.g. too short), not a failure — gets
            # its own status so it doesn't show up next to real problems,
            # and so the scraper's re-queue logic (which only resets
            # FAILED jobs) leaves it alone on rediscovery.
            logger.info(f"[transcriber] Excluding (not worth transcribing): {title} — {skip_reason}")
            await _update_job(jobs_col, job_id, {
                "status": JobStatus.EXCLUDED,
                "failed_stage": "transcription",
                "error": skip_reason,
            })
            # Same cleanup philosophy as everywhere else: download
            # everything, decide later, then delete what we don't keep.
            for path in file_paths:
                if os.path.exists(path) and path.endswith(".mp3"):
                    os.remove(path)
                    logger.info(f"[transcriber] Cleaned up (skipped): {path}")
            continue

        logger.info(f"\n[transcriber] Starting: {title}")
        logger.info(f"[transcriber] Captioned: {captioned}")

        # No separate "mark as processing" update here — claim_jobs()
        # already transitioned this job to PROCESSING atomically above.
        engine, engine_name = _pick_engine(job, vtt_path)
        done = False

        # Retry loop: attempt transcription up to MAX_RETRIES times in place
        # for this job, instead of marking it FAILED and waiting for a later
        # run_transcriptions() call (previously every ~30s via
        # transcriber_loop) to pick it back up. A VTT failure falls back to
        # Whisper without consuming a retry, since that's a one-time engine
        # switch rather than a retryable failure — only repeated Whisper
        # failures count against the retry budget.
        while retries < MAX_RETRIES and not done:
            if retries > 0:
                logger.warning(f"[transcriber] Retry attempt {retries + 1}/{MAX_RETRIES}")

            # Create a transcription task record for this attempt and
            # include the discovered file paths so each attempt is
            # auditable, including the VTT-to-Whisper fallback attempt
            # (previously that fallback reused the original task doc
            # instead of getting its own record).
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
                result = await engine.transcribe(audio_path)

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
                # Mark the transcription task as failed (best effort).
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
                    # Don't mask the original error if the task update fails
                    pass

                if engine_name == "vtt":
                    # One-time engine switch, not a retry — doesn't consume
                    # the retry budget. Loop immediately re-attempts with
                    # Whisper.
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
                    # Final give-up: clean up the audio file so a
                    # permanently-failed job doesn't hold onto disk space
                    # forever (previously only successful transcriptions
                    # triggered cleanup).
                    for path in file_paths:
                        if os.path.exists(path) and path.endswith(".mp3"):
                            os.remove(path)
                            logger.info(f"[transcriber] Cleaned up (gave up): {path}")
                else:
                    # Buffer before the next attempt instead of hammering
                    # the same failure immediately — doubles each retry
                    # (5s, 10s, ...). asyncio.sleep yields control, so
                    # scraper_loop/downloader_loop keep running during it.
                    delay = RETRY_DELAY_SECONDS * (2 ** (retries - 1))
                    logger.warning(f"[transcriber] Waiting {delay}s before retry...")
                    await asyncio.sleep(delay)