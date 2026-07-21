from datetime import datetime, timezone

def new_transcript(job_id: str, text: str, segments: list = []) -> dict:
    return {
        "job_id":     job_id,
        "text":       text,
        "segments":   segments,
        "created_at": datetime.now(timezone.utc),
    }