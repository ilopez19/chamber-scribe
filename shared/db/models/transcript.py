from datetime import datetime, timezone
from typing import Optional


# Builds a transcript document ready to insert into MongoDB; segments
# defaults to None (not []) to avoid a mutable default argument.
def new_transcript(job_id: str, text: str, segments: Optional[list] = None) -> dict:
    if segments is None:
        segments = []
    return {
        "job_id":     job_id,
        "text":       text,
        "segments":   segments,
        "created_at": datetime.now(timezone.utc),
    }
