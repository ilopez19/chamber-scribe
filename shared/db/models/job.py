"""Job-related models and factory helpers for storing work items.

This module declares the job lifecycle states and provides a helper to
construct a new job document with consistent audit fields. Keeping this in a
shared location ensures all services use the same field names and status
values.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    """Possible states for a video processing job.

    Use these enum values when reading/updating the database to avoid magic
    strings scattered throughout the codebase.
    """
    PENDING      = "pending"
    DOWNLOADING  = "downloading"
    DOWNLOADED   = "downloaded"
    PROCESSING   = "processing"
    TRANSCRIBED  = "transcribed"
    FAILED       = "failed"
    SKIPPED      = "skipped"


def new_video_job(video_url: str, source: str, metadata: Optional[dict] = None) -> dict:
    """Create a normalized job document for inserting into MongoDB.

    Args:
        video_url: Canonical URL used to identify and download the video.
        source: Short source name (must match detectors/portal registry).
        metadata: Optional portal-provided metadata; avoid using mutable
                  default arguments by passing None.

    Returns:
        A dict ready to upsert into the jobs collection.
    """
    # avoid mutable default argument
    if metadata is None:
        metadata = {}

    return {
        "video_url":      video_url, # url of video to download and transcribe
        "source":         source, # original source of the video (e.g. "michigan_house")
        "status":         JobStatus.PENDING, # initial state when queued
        "metadata":       metadata, # portal-specific metadata (title, duration, etc.)
        "retries":        0, # number of retry attempts at the current stage
        "error":          None, # last error message, if any
        "created_at":     datetime.now(timezone.utc),
        "updated_at":     datetime.now(timezone.utc),
        "downloaded_at":  None, # set when downloads succeed
        "transcribed_at": None, # set when transcription completes
    }