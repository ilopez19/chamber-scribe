from services.scraper.detectors.base import HTTPDetector
from services.scraper.http_utils import fetch_with_retry
from services.scraper.filter_utils import DeduplicationTracker
from services.scraper.metadata_utils import MetadataExtractor
from shared.logging_config import get_logger

logger = get_logger(__name__)

"""Detector for the Michigan Senate video portal.

This detector talks to the portal's paginated API to fetch all videos and emits
normalized video records for every video it finds. Deduplication within a
run is the only filtering done here — deciding whether a video is worth
downloading or transcribing (transcoding status, access level, duration,
etc.) is deliberately not this module's job. By design, everything gets
recorded; business rules about what's worth keeping live in one place
downstream (see should_transcribe() in services/transcriber/transcriber.py)
instead of being scattered across the scrape/download/transcribe stages.
This also means a video is never silently lost just because a filter check
happened to reject it here — if it's ever worth reconsidering, the data's
already captured.
"""

# Paginated API endpoint that returns all videos in the Senate catalog.
# Replaces the old tab-based API; this returns all videos with pagination support.
SENATE_ALL_VIDEOS_API_URL = "https://tf4pr3wftk.execute-api.us-west-2.amazonaws.com/default/api/all"

# Where the actual media files live once a video's ID is known — see
# rules.py, which builds the real download URL from CLOUDFRONT_BASE +
# portal_id. Distinct from the "Live Stream" channel entries, whose real
# location is a completely different path (vod_clients/.../live/chN/...)
# fetched from the portal's separate getLive/infoLive API — see rules.py.
CLOUDFRONT_BASE = "https://dlttx48mxf9m3.cloudfront.net/outputs"



class SenatePortalDetector(HTTPDetector):

    def __init__(self):
        # API is reasonably fast and uses valid SSL
        super().__init__(timeout=30, verify=True)
        # Deduplication tracker prevents duplicate videos within a single
        # scrape run (IDs are portal-provided). It's reset each run.
        self._dedup = DeduplicationTracker()

    @property
    def source_name(self) -> str:
        return "michigan_senate"

    async def get_new_videos(self) -> list[dict]:
        """Fetch all videos via pagination, deduplicate, and return records.

        The detector uses the DeduplicationTracker to ensure no duplicate
        videos are emitted from this run. Uses the single paginated /api/all
        endpoint instead of scraping individual tabs.
        """
        self._dedup = DeduplicationTracker()
        videos = []
        client = await self.get_client()

        page = 0
        while True:
            logger.info(f"[{self.source_name}] Fetching page {page}")
            try:
                # Fetch one page of results (up to 50 items per page)
                url = f"{SENATE_ALL_VIDEOS_API_URL}?page={page}&limit=50"
                response = await fetch_with_retry(client, url)
                data = response.json()

                # Extract items from paginated response
                items = data.get("record", []) if isinstance(data, dict) else data
                if not items:
                    # No more items — we've reached the end
                    logger.info(f"[{self.source_name}] Pagination complete (no items on page {page})")
                    break

                # Deduplicate items within this run
                unseen_items = self._dedup.get_unseen_videos(items, id_key="_id")

                for item in unseen_items:
                    filename = item.get("metadata", {}).get("filename", "untitled")
                    portal_id = str(item.get("_id"))
                    hls_url = f"{CLOUDFRONT_BASE}/{portal_id}/Default/HLS/out.m3u8"

                    metadata = MetadataExtractor.normalize_portal_metadata(
                        item=item,
                        source_name=self.source_name,
                        title=filename,
                        portal_id=portal_id,
                        original_date=item.get("original_date"),
                        captioned=item.get("captioned", False),
                        # No longer have a tab to record; omit or set to None
                        tab=None,
                        # Recorded but no longer used to filter — kept in
                        # case a future business rule downstream cares.
                        transcoded=item.get("transcoded", False),
                        access=item.get("access"),
                    )

                    video_record = MetadataExtractor.build_video_record(
                        video_url=hls_url,
                        metadata=metadata,
                    )

                    videos.append(video_record)
                    duration_mins = metadata.get("duration_mins", 0)
                    logger.info(f"[{self.source_name}] Found: {filename} ({duration_mins} mins)")

                # Move to next page
                page += 1

            except Exception as e:
                # Log the error but stop pagination (assume API is unhealthy)
                logger.warning(f"[{self.source_name}] Failed on page {page}: {e}")
                break

        logger.info(f"[{self.source_name}] Total unique videos found: {len(videos)}")
        return videos