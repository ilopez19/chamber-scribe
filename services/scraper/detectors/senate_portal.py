from services.scraper.detectors.base import HTTPDetector
from services.scraper.http_utils import fetch_with_retry
from services.scraper.filter_utils import VideoFilter, DeduplicationTracker
from services.scraper.metadata_utils import MetadataExtractor

"""Detector for the Michigan Senate video portal.

This detector talks to the portal's JSON API across multiple tabs and emits
normalized video records. It applies filters for transcoding status and
access level to avoid queuing videos that are not ready or are restricted.
"""

BASE_URL = "https://2kbyogxrg4.execute-api.us-west-2.amazonaws.com/61b3adc8124d7d000891ca5c"
CLOUDFRONT_BASE = "https://dlttx48mxf9m3.cloudfront.net/outputs"

TABS = {
    "home":      "home/home",
    "live":      "home/live",
    "recent":    "home/recent",
    "playlists": "home/playlists",
    "featured":  "home/featured",
    "popular":   "home/popular",
}


class CouncilPortalDetector(HTTPDetector):

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
            print(f"[{self.source_name}] Scraping tab: {tab_name}")
            try:
                response = await fetch_with_retry(client, f"{BASE_URL}/{tab_path}")
                data = response.json()

                items = data if isinstance(data, list) else data.get("results", [])
                unseen_items = self._dedup.get_unseen_videos(items, id_key="_id")

                for item in unseen_items:
                    # Skip if the video hasn't finished server-side transcoding
                    if not VideoFilter.filter_by_transcoding(item, required=True):
                        print(f"[{self.source_name}] Skipping untranscoded: {item.get('_id')}")
                        continue

                    # Respect access restrictions — only queue open videos
                    if not VideoFilter.filter_by_access_level(item, required_access="open"):
                        print(f"[{self.source_name}] Skipping restricted: {item.get('_id')}")
                        continue

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
                    )

                    video_record = MetadataExtractor.build_video_record(
                        video_url=hls_url,
                        metadata=metadata,
                    )

                    videos.append(video_record)
                    duration_mins = metadata.get("duration_mins", 0)
                    print(f"[{self.source_name}] Found: {filename} ({duration_mins} mins)")

            except Exception as e:
                # Don't stop the whole scrape on a single tab failure; keep
                # trying remaining tabs so partial data can still be retrieved.
                print(f"[{self.source_name}] Failed on tab {tab_name}: {e}")
                continue

        print(f"[{self.source_name}] Total unique videos found: {len(videos)}")
        return videos