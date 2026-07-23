from datetime import datetime, timezone
from enum import Enum
from typing import Optional

# Python immediately crashes with an AttributeError, catching the bug instantly
class JobStatus(str, Enum):
    PENDING     = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED   = "downloaded"
    PROCESSING  = "processing"
    TRANSCRIBED = "transcribed"
    FAILED      = "failed"
    SKIPPED     = "skipped"

def new_video_job(video_url: str, source: str, metadata: Optional[dict] = None) -> dict:
    # avoid mutable default argument
    if metadata is None:
        metadata = {}

    return {
        "video_url":      video_url, # url of video to download and transcribe
        "source":         source, # original source of the video (e.g. "michigan_house")
        "status":         JobStatus.PENDING, # current status of the job (pending, downloading, processing, transcribed, failed)
        "metadata":       metadata, # additional metadata about the video (e.g. title, duration, date, etc.)
        "retries":        0, # number of retries at the state it's in
        "error":          None, # error message if the job fails
        "created_at":     datetime.now(timezone.utc),
        "updated_at":     datetime.now(timezone.utc),
        "downloaded_at":  None, # timestamp when the video was downloaded
        "transcribed_at": None, # timestamp when the video was transcribed
    }