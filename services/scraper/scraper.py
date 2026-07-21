from shared.db.database import jobs_collection
from shared.db.models.job import new_job
from services.scraper.detectors.portal_a import CouncilPortalDetector
from services.scraper.detectors.house_portal import HousePortalDetector

DETECTORS = [
    CouncilPortalDetector(),
    HousePortalDetector(),
]

async def run_scrape():
    collection = jobs_collection()
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

            existing = await collection.find_one({"video_url": url})
            if existing:
                print(f"[scraper] Already seen, skipping: {url}")
                continue

            job = new_job(
                video_url=url,
                source=detector.source_name,
                metadata=video.get("metadata", {})
            )
            result = await collection.insert_one(job)
            print(f"[scraper] New job created: {result.inserted_id} — {video['metadata']['title']}")
            total_new += 1

    print(f"[scraper] Done. {total_new} new job(s) queued.")