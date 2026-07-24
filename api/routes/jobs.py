from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId
from shared.db.database import jobs_collection

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _serialize(job: dict) -> dict:
    """Convert MongoDB document to JSON-safe dict."""
    job["id"] = str(job.pop("_id"))
    return job


@router.get("/summary")
async def get_summary():
    """Count of jobs by status."""
    col = jobs_collection()
    statuses = ["pending", "downloading", "downloaded", "processing", "transcribed", "failed", "skipped"]
    summary = {}
    for status in statuses:
        count = await col.count_documents({"status": status})
        if count > 0:
            summary[status] = count
    summary["total"] = await col.count_documents({})
    return summary


@router.get("/")
async def list_jobs(
        status: str = Query(None, description="Filter by status"),
        source: str = Query(None, description="Filter by source e.g. michigan_senate"),
        limit: int = Query(50, le=200),
        skip: int = Query(0),
):
    """List jobs with optional filters."""
    col = jobs_collection()
    query = {}
    if status:
        query["status"] = status
    if source:
        query["source"] = source

    cursor = col.find(query).skip(skip).limit(limit).sort("created_at", -1)
    jobs = await cursor.to_list(length=limit)
    return {
        "total": await col.count_documents(query),
        "skip": skip,
        "limit": limit,
        "jobs": [_serialize(j) for j in jobs],
    }


@router.get("/{job_id}")
async def get_job(job_id: str):
    """Get a single job by ID."""
    col = jobs_collection()
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    job = await col.find_one({"_id": oid})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return _serialize(job)