from odmantic import Model
from typing import Optional, Any
from datetime import datetime


class Task(Model):
    id: Optional[str]
    job_id: Optional[str]
    task_type: Optional[str]
    status: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        extra = "allow"
