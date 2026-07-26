# Job lifecycle states + a factory for new job documents, kept in one
# shared place so every service uses the same field names and statuses.

from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# States a video job moves through: scrape -> download -> transcribe.
class JobStatus(str, Enum):

    PENDING     = "pending"      # queued, not yet picked up
    DOWNLOADING = "downloading"  # downloader is actively fetching the video
    DOWNLOADED  = "downloaded"   # audio/captions saved to disk, ready to transcribe
    PROCESSING  = "processing"   # transcription in progress
    TRANSCRIBED = "transcribed"  # done — transcript exists in the transcripts collection

    # A genuine error, retried up to JOB_MAX_RETRIES then re-queued if
    # rediscovered. This is the status to check when triaging problems.
    FAILED = "failed"

    # A deliberate business-rule exclusion (e.g. too short, live-channel
    # entry), not an error — never retried, since the reason won't change.
    EXCLUDED = "excluded"


# Builds a job document ready to insert into MongoDB; metadata defaults
# to None (not {}) to avoid a mutable default argument.
def new_video_job(video_url: str, source: str, metadata: Optional[dict] = None) -> dict:
    if metadata is None:
        metadata = {}

    return {
        "video_url":      video_url,
        "captioned":      metadata.get("captioned", False),
        "source":         source,                  # e.g. "michigan_house"
        "status":         JobStatus.PENDING,
        "metadata":       metadata,                # portal-specific: title, duration, etc.
        "retries":        0,
        "error":          None,
        "created_at":     datetime.now(timezone.utc),
        "updated_at":     datetime.now(timezone.utc),
        "downloaded_at":  None,                     # set when downloads succeed
        "transcribed_at": None,                     # set when transcription completes
    }
