from datetime import datetime, timezone
from typing import Optional


# Builds a minimal transcription task document (one per attempt);
# status is one of pending | processing | done | failed.
def new_task(job_id: str, task_type: str = "transcription", metadata: Optional[dict] = None) -> dict:
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
