from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId
from shared.db.database import tasks_collection

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _serialize(task: dict) -> dict:
    """Convert MongoDB document to JSON-safe dict."""
    task["id"] = str(task.pop("_id"))
    return task


@router.get("/summary")
async def get_summary():
    """Count of tasks by status."""
    col = tasks_collection()
    statuses = ["pending", "processing", "done", "failed"]
    summary = {}
    for status in statuses:
        count = await col.count_documents({"status": status})
        if count > 0:
            summary[status] = count
    summary["total"] = await col.count_documents({})
    return summary


@router.get("/")
async def list_tasks(
        job_id: str = Query(None, description="Filter by job_id"),
        status: str = Query(None, description="Filter by status"),
        task_type: str = Query(None, description="Filter by task_type e.g. transcription"),
        limit: int = Query(50, le=200),
        skip: int = Query(0),
):
    """List transcription attempt records, most recent first."""
    col = tasks_collection()
    query = {}
    if job_id:
        query["job_id"] = job_id
    if status:
        query["status"] = status
    if task_type:
        query["task_type"] = task_type

    cursor = col.find(query).skip(skip).limit(limit).sort("created_at", -1)
    tasks = await cursor.to_list(length=limit)
    return {
        "total": await col.count_documents(query),
        "skip": skip,
        "limit": limit,
        "tasks": [_serialize(t) for t in tasks],
    }


@router.get("/{task_id}")
async def get_task(task_id: str):
    """Get a single task attempt by ID."""
    col = tasks_collection()
    try:
        oid = ObjectId(task_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    task = await col.find_one({"_id": oid})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return _serialize(task)
