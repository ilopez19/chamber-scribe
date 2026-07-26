# Job endpoints: summary counts, listing (filterable), and lookup by ID.
from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId
from shared.db.database import jobs_collection
from api.serialization import serialize_document

router = APIRouter(prefix="/jobs", tags=["jobs"])


# Counts jobs grouped by status, plus a "total" key; statuses with zero
# jobs are left out entirely rather than shown as 0.
# Returns e.g. {"pending": 3, "transcribed": 128, "total": 145}.
@router.get("/summary", summary="Job counts by status")
async def get_summary():
    col = jobs_collection()
    statuses = ["pending", "downloading", "downloaded", "processing", "transcribed", "failed", "excluded"]
    summary = {}
    for status in statuses:
        count = await col.count_documents({"status": status})
        if count > 0:
            summary[status] = count
    summary["total"] = await col.count_documents({})
    return summary


# Lists jobs, most recent first, optionally filtered by status and/or source.
# Returns {total, skip, limit, jobs: [{id, status, source, metadata, ...}]}.
@router.get("/", summary="List jobs")
async def list_jobs(
        status: str = Query(None, description="Filter by status"),
        source: str = Query(None, description="Filter by source e.g. michigan_senate"),
        limit: int = Query(50, le=200),
        skip: int = Query(0),
):
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
        "jobs": [serialize_document(j) for j in jobs],
    }


# Gets a single job by its own Mongo ID.
# Returns {id, status, source, video_url, metadata, retries, error, ...}.
@router.get("/{job_id}", summary="Get a job by ID")
async def get_job(job_id: str):
    col = jobs_collection()
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    job = await col.find_one({"_id": oid})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return serialize_document(job)
