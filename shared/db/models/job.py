from datetime import datetime, timezone

class JobStatus:
    PENDING     = "pending"
    DOWNLOADING = "downloading"
    PROCESSING  = "processing"
    TRANSCRIBED = "transcribed"
    FAILED      = "failed"
    SKIPPED     = "skipped"

def new_job(video_url: str, source: str, metadata: dict = {}) -> dict:
    return {
        "video_url":      video_url,
        "source":         source,
        "status":         JobStatus.PENDING,
        "metadata":       metadata,
        "retries":        0,
        "error":          None,
        "created_at":     datetime.now(timezone.utc),
        "updated_at":     datetime.now(timezone.utc),
        "downloaded_at":  None,
        "transcribed_at": None,
    }