from services.scraper.detectors.base import HTTPDetector
from services.scraper.http_utils import fetch_with_retry
from services.scraper.filter_utils import VideoFilter, DeduplicationTracker
from services.scraper.metadata_utils import MetadataExtractor

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
        super().__init__(timeout=30, verify=True)
        self._dedup = DeduplicationTracker()

    @property
    def source_name(self) -> str:
        return "michigan_senate"

    async def get_new_videos(self) -> list[dict]:
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
                    if not VideoFilter.filter_by_transcoding(item, required=True):
                        print(f"[{self.source_name}] Skipping untranscoded: {item.get('_id')}")
                        continue

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
                print(f"[{self.source_name}] Failed on tab {tab_name}: {e}")
                continue

        print(f"[{self.source_name}] Total unique videos found: {len(videos)}")
        return videos