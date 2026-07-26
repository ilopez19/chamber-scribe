# Tests for claim_jobs() — the atomic job-claiming helper that makes it
# safe to run the downloader/transcriber pickup step concurrently. Uses an
# in-memory fake collection instead of a real database, since this tests
# claim_jobs()'s logic, not the Mongo driver.

import asyncio

import pytest

from shared.db.database import claim_jobs


def _matches_condition(doc: dict, condition: dict) -> bool:
    for key, expected in condition.items():
        if isinstance(expected, dict):
            if "$lt" in expected and not (doc.get(key, 0) < expected["$lt"]):
                return False
            if "$exists" in expected and (key in doc) != expected["$exists"]:
                return False
        elif doc.get(key) != expected:
            return False
    return True


def _matches(doc: dict, query: dict) -> bool:
    if "$or" in query:
        if not any(_matches(doc, cond) for cond in query["$or"]):
            return False
        remaining = {k: v for k, v in query.items() if k != "$or"}
        return _matches_condition(doc, remaining)
    return _matches_condition(doc, query)


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return list(self._docs)


# Just enough of a pymongo collection to exercise claim_jobs()'s
# query/update semantics, including the atomicity guarantee update_many gives.
class FakeCollection:

    def __init__(self, docs):
        self._docs = {d["_id"]: dict(d) for d in docs}
        self._lock = asyncio.Lock()

    async def update_many(self, query, update):
        # The lock simulates Mongo's per-document atomicity so two
        # concurrent callers can't interleave match-then-apply on the same doc.
        async with self._lock:
            matched = [d for d in self._docs.values() if _matches(d, query)]
            for doc in matched:
                doc.update(update["$set"])

    def find(self, query):
        matched = [dict(d) for d in self._docs.values() if _matches(d, query)]
        return FakeCursor(matched)


@pytest.mark.asyncio
async def test_claim_jobs_returns_only_matching_documents():
    col = FakeCollection([
        {"_id": 1, "status": "pending"},
        {"_id": 2, "status": "downloaded"},
    ])
    claimed = await claim_jobs(col, {"status": "pending"}, claimed_status="downloading")
    assert [d["_id"] for d in claimed] == [1]
    assert col._docs[1]["status"] == "downloading"
    assert col._docs[2]["status"] == "downloaded"  # untouched


@pytest.mark.asyncio
async def test_claim_jobs_tags_claimed_documents_with_a_unique_claim_id():
    col = FakeCollection([{"_id": 1, "status": "pending"}])
    claimed = await claim_jobs(col, {"status": "pending"}, claimed_status="downloading")
    assert "claim_id" in claimed[0]
    assert col._docs[1]["claim_id"] == claimed[0]["claim_id"]


@pytest.mark.asyncio
async def test_two_concurrent_claims_never_claim_the_same_job():
    # The actual regression this guards: two overlapping callers racing to
    # pick up the same batch of pending jobs.
    docs = [{"_id": i, "status": "pending"} for i in range(20)]
    col = FakeCollection(docs)

    results = await asyncio.gather(
        claim_jobs(col, {"status": "pending"}, claimed_status="downloading"),
        claim_jobs(col, {"status": "pending"}, claimed_status="downloading"),
    )

    ids_a = {d["_id"] for d in results[0]}
    ids_b = {d["_id"] for d in results[1]}

    assert ids_a.isdisjoint(ids_b), "the same job was claimed by both concurrent callers"
    assert ids_a | ids_b == {d["_id"] for d in docs}


@pytest.mark.asyncio
async def test_or_query_with_lt_condition_matches_downloader_style_query():
    col = FakeCollection([
        {"_id": 1, "status": "pending"},
        {"_id": 2, "status": "failed", "failed_stage": "download", "retries": 1},
        {"_id": 3, "status": "failed", "failed_stage": "download", "retries": 5},
        {"_id": 4, "status": "excluded"},
    ])
    claimed = await claim_jobs(
        col,
        query={
            "$or": [
                {"status": "pending"},
                {"status": "failed", "failed_stage": "download", "retries": {"$lt": 3}},
            ]
        },
        claimed_status="downloading",
    )
    ids = {d["_id"] for d in claimed}
    # Not 3 (retries exhausted) and not 4 (excluded — different status,
    # and by design never reset back to pending/failed for reclaiming).
    assert ids == {1, 2}
