from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId
from shared.db.database import transcripts_collection, jobs_collection

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/")
async def list_transcripts(
        limit: int = Query(50, le=200),
        skip: int = Query(0),
):
    """List all transcripts."""
    col = transcripts_collection()
    cursor = col.find().skip(skip).limit(limit).sort("created_at", -1)
    docs = await cursor.to_list(length=limit)
    return {
        "total": await col.count_documents({}),
        "skip": skip,
        "limit": limit,
        "transcripts": [_serialize(d) for d in docs],
    }


@router.get("/search")
async def search_transcripts(
        q: str = Query(..., description="Search term"),
        limit: int = Query(20, le=100),
):
    col = transcripts_collection()
    cursor = col.find(
        {"$text": {"$search": q}},
        {"score": {"$meta": "textScore"}}
    ).sort([("score", {"$meta": "textScore"})]).limit(limit)
    docs = await cursor.to_list(length=limit)
    return {"query": q, "results": len(docs), "transcripts": [_serialize(d) for d in docs]}


@router.get("/{job_id}")
async def get_transcript(job_id: str):
    """Get transcript for a specific job."""
    col = transcripts_collection()
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID")

    # Try by transcript ID first
    doc = await col.find_one({"_id": oid})

    # Fall back to job_id lookup
    if not doc:
        doc = await col.find_one({"job_id": job_id})

    if not doc:
        raise HTTPException(status_code=404, detail="Transcript not found")

    # Enrich with job metadata
    job = await jobs_collection().find_one({"_id": ObjectId(doc["job_id"])})
    if job:
        doc["job_title"] = job.get("metadata", {}).get("title")
        doc["job_source"] = job.get("source")
        doc["original_date"] = job.get("metadata", {}).get("original_date")

    return _serialize(doc)