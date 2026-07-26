from datetime import datetime, timezone
from typing import Optional


def new_task(job_id: str, task_type: str = "transcription", metadata: Optional[dict] = None) -> dict:
    """Create a minimal transcription task document.

    Fields:
      - job_id: stringified job _id
      - task_type: e.g. "transcription"
      - status: pending | processing | done | failed
      - retries, error, metadata, timestamps, started_at, finished_at, result_id
    """
    if metadata is None:
        metadata = {}
    return {
        "job_id": job_id,
        "task_type": task_type,
        "status": "pending",
        "retries": 0,
        "error": None,
        "metadata": metadata,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "started_at": None,
        "finished_at": None,
        "result_id": None,
    }


