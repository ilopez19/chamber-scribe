from datetime import datetime, timezone

from shared.db.database import jobs_collection
from shared.db.models.job import new_video_job
from services.scraper.detectors.senate_portal import CouncilPortalDetector
from services.scraper.detectors.house_portal import HousePortalDetector

DETECTORS = [
    CouncilPortalDetector(),
    HousePortalDetector(),
    # add new detectors here as needed
]


async def run_scrape():
    collection = jobs_collection()
    # Ensure a unique index on video_url to make inserts idempotent across workers
    # create_index is idempotent and cheap when the index already exists
    try:
        await collection.create_index("video_url", unique=True)
    except Exception as e:
        print(f"[scraper] Warning: failed to create index on video_url: {e}")
    total_new = 0

    for detector in DETECTORS:
        print(f"[scraper] Running detector: {detector.source_name}")
        try:
            videos = await detector.get_new_videos()
        except Exception as e:
            print(f"[scraper] Detector {detector.source_name} crashed: {e}")
            continue

        for video in videos:
            url = video["video_url"]

            # Build the job document (timestamps set inside new_video_job)
            job = new_video_job(
                video_url=url,
                source=detector.source_name,
                metadata=video.get("metadata", {})
            )

            # Atomic insert-if-not-exists using $setOnInsert. If another worker
            # created the document concurrently, upsert will not create a duplicate.
            try:
                res = await collection.update_one(
                    {"video_url": url},
                    {"$setOnInsert": job},
                    upsert=True,
                )
            except Exception as e:
                print(f"[scraper] Failed to upsert job for {url}: {e}")
                continue

            # If upserted_id is present, this call inserted the document
            if getattr(res, "upserted_id", None):
                print(f"[scraper] New job created: {res.upserted_id} — {video.get('metadata', {}).get('title')}")
                total_new += 1
            else:
                # Already existed; update 'updated_at' to reflect last seen
                try:
                    await collection.update_one({"video_url": url}, {"$set": {"updated_at": datetime.now(timezone.utc)}})
                except Exception:
                    pass
                print(f"[scraper] Already seen, skipping: {url}")

    print(f"[scraper] Done. {total_new} new job(s) queued.")