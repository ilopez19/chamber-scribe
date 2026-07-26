from services.scraper.detectors.base import HTTPDetector
from services.scraper.http_utils import fetch_with_retry
from services.scraper.filter_utils import DeduplicationTracker
from services.scraper.metadata_utils import MetadataExtractor
from shared.media_urls import AUDIO_URL_TEMPLATE
from shared.logging_config import get_logger

logger = get_logger(__name__)

# Detector for the Michigan Senate video portal. Records every video found
# with no filtering — business rules about what's worth keeping live
# downstream in should_transcribe() (services/transcriber/transcriber.py).

# Paginated API that returns the whole Senate catalog. As of 2026-07 this
# is POST-only with a small JSON body (the old GET+query-string contract
# now gets rejected outright); the real front-end is cloud.castus.tv/vod/misenate.
SENATE_ALL_VIDEOS_API_URL = "https://tf4pr3wftk.execute-api.us-west-2.amazonaws.com/default/api/all"

# The Senate's own channel ID within the Castus-backed API, not a per-video
# ID — sent as the `_id` field in every request body below.
SENATE_CHANNEL_ID = "61b3adc8124d7d000891ca5c"

# Same page size as the old API's ?limit=50, just named "results" now.
PAGE_SIZE = 50

# Headers copied from the real front-end's request — the API rejects
# requests whose Origin/Referer don't match these.
SENATE_REQUEST_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://cloud.castus.tv",
    "Referer": "https://cloud.castus.tv/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


class SenatePortalDetector(HTTPDetector):

    def __init__(self):
        # API is reasonably fast and uses valid SSL
        super().__init__(timeout=30, verify=True)
        self._dedup = DeduplicationTracker()

    SOURCE_NAME = "michigan_senate"
    DISPLAY_NAME = "Michigan Senate"

    @property
    def source_name(self) -> str:
        return self.SOURCE_NAME

    # Fetches all videos via pagination, deduplicates, and returns records.
    async def get_new_videos(self) -> list[dict]:
        self._dedup = DeduplicationTracker()
        videos = []
        client = await self.get_client()

        # Pagination is 1-based now (was 0-based under the old API).
        page = 1
        while True:
            logger.info(f"[{self.SOURCE_NAME}] Fetching page {page}")
            try:
                body = {"_id": SENATE_CHANNEL_ID, "page": page, "results": PAGE_SIZE}
                response = await fetch_with_retry(
                    client,
                    SENATE_ALL_VIDEOS_API_URL,
                    method="POST",
                    json=body,
                    headers=SENATE_REQUEST_HEADERS,
                )
                data = response.json()

                # "record" is now an int total, not the item list —
                # items live under "allFiles" instead.
                items = data.get("allFiles", []) if isinstance(data, dict) else data
                if not items:
                    logger.info(f"[{self.SOURCE_NAME}] Pagination complete (no items on page {page})")
                    break

                unseen_items = self._dedup.get_unseen_videos(items, id_key="_id")

                for item in unseen_items:
                    filename = item.get("metadata", {}).get("filename", "untitled")
                    portal_id = str(item.get("_id"))
                    # Same template the downloader uses at download time
                    # (shared/media_urls.py) so the two can't drift apart.
                    hls_url = AUDIO_URL_TEMPLATE.format(portal_id=portal_id)

                    # `captioned` now comes back as a list (e.g. [true]);
                    # normalize to bool since downstream does `if captioned:`
                    # and a non-empty list is truthy even when it's [false].
                    captioned_raw = item.get("captioned", False)
                    if isinstance(captioned_raw, list):
                        captioned = bool(captioned_raw[0]) if captioned_raw else False
                    else:
                        captioned = bool(captioned_raw)

                    metadata = MetadataExtractor.normalize_portal_metadata(
                        item=item,
                        source_name=self.SOURCE_NAME,
                        title=filename,
                        portal_id=portal_id,
                        original_date=item.get("original_date"),
                        captioned=captioned,
                        tab=None,
                        transcoded=item.get("transcoded", False),
                        access=item.get("access"),
                    )

                    video_record = MetadataExtractor.build_video_record(
                        video_url=hls_url,
                        metadata=metadata,
                    )

                    videos.append(video_record)
                    duration_mins = metadata.get("duration_mins", 0)
                    logger.info(f"[{self.SOURCE_NAME}] Found: {filename} ({duration_mins} mins)")

                page += 1

            except Exception as e:
                # Log the error but stop pagination (assume API is unhealthy)
                logger.warning(f"[{self.SOURCE_NAME}] Failed on page {page}: {e}")
                break

        logger.info(f"[{self.source_name}] Total unique videos found: {len(videos)}")
        return videos
