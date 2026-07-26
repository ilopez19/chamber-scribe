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
#
# As of 2026-07, this is a POST-only endpoint (a GET with ?page=&limit= query
# params — the old contract — now gets rejected outright, either with a bare
# 403 or a "Missing Authentication Token" body, which for API Gateway usually
# just means "no route matches this request" rather than a literal auth
# problem). The real front-end (cloud.castus.tv/vod/misenate — the Senate's
# video catalog appears to now be hosted on Castus) sends a POST with a small
# JSON body instead, captured directly from that page's network requests:
#   POST /default/api/all
#   Body: {"_id": SENATE_CHANNEL_ID, "page": <1-based>, "results": <page size>}
# The endpoint also appears to check Origin/Referer against the real
# front-end — requests missing those were part of what got rejected — so
# every request below sends the same headers the real front-end sends.
SENATE_ALL_VIDEOS_API_URL = "https://tf4pr3wftk.execute-api.us-west-2.amazonaws.com/default/api/all"

# Fixed Mongo ObjectId identifying the Senate's own channel/account within
# the (apparently shared, Castus-backed) API — not a per-video ID. Sent as
# the `_id` field in every request body above. Captured from the real
# front-end's request payload; if the Senate ever moves to a different
# Castus account this would need to be re-captured the same way.
SENATE_CHANNEL_ID = "61b3adc8124d7d000891ca5c"

# Matches the old GET API's ?limit=50 page size — the field is just named
# "results" instead of "limit" in the new POST body.
PAGE_SIZE = 50

# Headers copied verbatim from the real front-end's request (DevTools →
# Network → the POST to this same URL from cloud.castus.tv). The API
# appears to reject requests whose Origin/Referer don't match, which is
# most of what made the old plain GET fail.
SENATE_REQUEST_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://cloud.castus.tv",
    "Referer": "https://cloud.castus.tv/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# Where the actual media files live once a video's ID is known — see
# rules.py, which builds the real download URL from CLOUDFRONT_BASE +
# portal_id. Distinct from the "Live Stream" channel entries, whose real
# location is a completely different path (vod_clients/.../live/chN/...)
# fetched from the portal's separate getLive/infoLive API — see rules.py.
# NOTE: unverified against the new POST-based /api/all contract above — if
# downloads start failing for non-live Senate videos, this is the first
# place to check (the video catalog API moved; the actual media host may
# have moved with it).
CLOUDFRONT_BASE = "https://dlttx48mxf9m3.cloudfront.net/outputs"



class SenatePortalDetector(HTTPDetector):

    def __init__(self):
        # API is reasonably fast and uses valid SSL
        super().__init__(timeout=30, verify=True)
        # Deduplication tracker prevents duplicate videos within a single
        # scrape run (IDs are portal-provided). It's reset each run.
        self._dedup = DeduplicationTracker()

    SOURCE_NAME = "michigan_senate"
    DISPLAY_NAME = "Michigan Senate"

    @property
    def source_name(self) -> str:
        return self.SOURCE_NAME

    async def get_new_videos(self) -> list[dict]:
        """Fetch all videos via pagination, deduplicate, and return records.

        The detector uses the DeduplicationTracker to ensure no duplicate
        videos are emitted from this run. Uses the single paginated /api/all
        endpoint instead of scraping individual tabs.
        """
        self._dedup = DeduplicationTracker()
        videos = []
        client = await self.get_client()

        # Pagination is 1-based now (was 0-based under the old GET+query-string
        # API) — confirmed from the real front-end's request body.
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

                # Response shape is {"record": <total count across all pages>,
                # "allFiles": [...], "count": <items in this page>} — NOT
                # {"record": [...]} like the old GET API. "record" is an int
                # total here, not the list of items.
                items = data.get("allFiles", []) if isinstance(data, dict) else data
                if not items:
                    # No more items — we've reached the end
                    logger.info(f"[{self.SOURCE_NAME}] Pagination complete (no items on page {page})")
                    break

                # Deduplicate items within this run
                unseen_items = self._dedup.get_unseen_videos(items, id_key="_id")

                for item in unseen_items:
                    filename = item.get("metadata", {}).get("filename", "untitled")
                    portal_id = str(item.get("_id"))
                    hls_url = f"{CLOUDFRONT_BASE}/{portal_id}/Default/HLS/out.m3u8"

                    # `captioned` now comes back as a list (e.g. [true])
                    # instead of a plain bool. Normalize it here — downstream
                    # (services/downloader/rules.py) does `if captioned:`,
                    # and a non-empty list is truthy even when it's [false],
                    # which would silently route every video down the wrong
                    # download path.
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
                    logger.info(f"[{self.SOURCE_NAME}] Found: {filename} ({duration_mins} mins)")

                # Move to next page
                page += 1

            except Exception as e:
                # Log the error but stop pagination (assume API is unhealthy)
                logger.warning(f"[{self.SOURCE_NAME}] Failed on page {page}: {e}")
                break

        logger.info(f"[{self.source_name}] Total unique videos found: {len(videos)}")
        return videos