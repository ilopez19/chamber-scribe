# Task endpoints: summary counts, listing (filterable), and lookup by ID.
# A "task" is one transcription attempt — a job can have several.
from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId
from shared.db.database import tasks_collection
from api.serialization import serialize_document

router = APIRouter(prefix="/tasks", tags=["tasks"])


# Counts tasks grouped by status, plus a "total" key; statuses with zero
# tasks are left out entirely rather than shown as 0.
# Returns e.g. {"done": 128, "failed": 3, "total": 132}.
@router.get("/summary", summary="Task counts by status")
async def get_summary():
    col = tasks_collection()
    statuses = ["pending", "processing", "done", "failed"]
    summary = {}
    for status in statuses:
        count = await col.count_documents({"status": status})
        if count > 0:
            summary[status] = count
    summary["total"] = await col.count_documents({})
    return summary


# Lists transcription attempt records, most recent first — each is one
# attempt (a job can have several across retries), not the job itself.
# Returns {total, skip, limit, tasks: [{id, job_id, status, engine, ...}]}.
@router.get("/", summary="List transcription tasks")
async def list_tasks(
        job_id: str = Query(None, description="Filter by job_id"),
        status: str = Query(None, description="Filter by status"),
        task_type: str = Query(None, description="Filter by task_type e.g. transcription"),
        limit: int = Query(50, le=200),
        skip: int = Query(0),
):
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
        "tasks": [serialize_document(t) for t in tasks],
    }


# Gets a single transcription attempt record by its own Mongo ID.
# Returns {id, job_id, status, retries, error, result_id, ...}.
@router.get("/{task_id}", summary="Get a task by ID")
async def get_task(task_id: str):
    col = tasks_collection()
    try:
        oid = ObjectId(task_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    task = await col.find_one({"_id": oid})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return serialize_document(task)
