# Transcript endpoints: listing, full-text search, and lookup by ID or job_id.
from fastapi import APIRouter, HTTPException, Path, Query
from bson import ObjectId
from shared.db.database import transcripts_collection, jobs_collection
from api.serialization import serialize_document

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


# Lists all transcripts, most recent first.
# Returns {total, skip, limit, transcripts: [{id, job_id, text, segments, ...}]}.
@router.get("/", summary="List transcripts")
async def list_transcripts(
        limit: int = Query(50, le=200),
        skip: int = Query(0),
):
    col = transcripts_collection()
    cursor = col.find().skip(skip).limit(limit).sort("created_at", -1)
    docs = await cursor.to_list(length=limit)
    return {
        "total": await col.count_documents({}),
        "skip": skip,
        "limit": limit,
        "transcripts": [serialize_document(d) for d in docs],
    }


# Full-text search over transcript text, ranked by relevance.
# Returns {query, results, transcripts: [...]}.
@router.get("/search", summary="Search transcripts")
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
    return {"query": q, "results": len(docs), "transcripts": [serialize_document(d) for d in docs]}


# Gets a transcript, looked up by its own ID first, then by job_id; also
# enriches the response with job_title/job_source/original_date from the
# parent job, when it still exists.
# Returns {id, job_id, text, segments, engine, job_title, ...}.
@router.get("/{job_id}", summary="Get a transcript")
async def get_transcript(
        job_id: str = Path(..., description="Either the transcript's own ID or the ID of the job it belongs to — both are accepted."),
):
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

    return serialize_document(doc)
