from services.scraper.detectors.base import HTTPDetector
from services.scraper.http_utils import fetch_with_retry
from services.scraper.filter_utils import DeduplicationTracker
from services.scraper.metadata_utils import MetadataExtractor
from shared.logging_config import get_logger

logger = get_logger(__name__)

"""Detector for the Michigan Senate video portal.

This detector talks to the portal's JSON API across multiple tabs and emits
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

# AWS API Gateway endpoint that serves the Senate's video catalog listings
# (the six tabs below) as JSON — this is the API backing
# cloud.castus.tv/vod/misenate, not something we host. The trailing path
# segment (61b3adc8...) is this portal's fixed catalog/site ID within
# that API, not a per-video identifier.
SENATE_CATALOG_API_BASE_URL = "https://2kbyogxrg4.execute-api.us-west-2.amazonaws.com/61b3adc8124d7d000891ca5c"

# Where the actual media files live once a video's ID is known — see
# rules.py, which builds the real download URL from CLOUDFRONT_BASE +
# portal_id. Distinct from the "Live Stream" channel entries, whose real
# location is a completely different path (vod_clients/.../live/chN/...)
# fetched from the portal's separate getLive/infoLive API — see rules.py.
CLOUDFRONT_BASE = "https://dlttx48mxf9m3.cloudfront.net/outputs"

TABS = {
    "home":      "home/home",
    "live":      "home/live",
    "recent":    "home/recent",
    "playlists": "home/playlists",
    "featured":  "home/featured",
    "popular":   "home/popular",
}


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
        """Fetch videos across tabs, normalize, and return unique records.

        The detector uses the DeduplicationTracker to ensure the same video
        appearing in multiple tabs is only processed once per run.
        """
        self._dedup = DeduplicationTracker()
        videos = []
        client = await self.get_client()

        for tab_name, tab_path in TABS.items():
            logger.info(f"[{self.source_name}] Scraping tab: {tab_name}")
            try:
                response = await fetch_with_retry(client, f"{SENATE_CATALOG_API_BASE_URL}/{tab_path}")
                data = response.json()

                items = data if isinstance(data, list) else data.get("results", [])
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
                        tab=tab_name,
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

            except Exception as e:
                # Don't stop the whole scrape on a single tab failure; keep
                # trying remaining tabs so partial data can still be retrieved.
                logger.warning(f"[{self.source_name}] Failed on tab {tab_name}: {e}")
                continue

        logger.info(f"[{self.source_name}] Total unique videos found: {len(videos)}")
        return videos