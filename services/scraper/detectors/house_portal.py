# Scrapes the Michigan House's public video archive page (HTML, not an API).
import warnings
from bs4 import BeautifulSoup
from services.scraper.detectors.base import HTTPDetector
from services.scraper.http_utils import fetch_with_retry
from services.scraper.filter_utils import DeduplicationTracker
from services.scraper.metadata_utils import MetadataExtractor
from shared.logging_config import get_logger

logger = get_logger(__name__)

# The House site has cert problems; the HTTP strategy disables verification
# for this host, so silence the resulting warnings here too.
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

BASE_URL = "https://house.mi.gov"
LISTING_URL = f"{BASE_URL}/VideoArchive"
DOWNLOAD_BASE = f"{BASE_URL}/ArchiveVideoFiles"


class HousePortalDetector(HTTPDetector):

    def __init__(self):
        # Server uses invalid certs; detector and strategies handle verification
        super().__init__(timeout=30, verify=False)
        self._dedup = DeduplicationTracker()

    SOURCE_NAME = "michigan_house"
    DISPLAY_NAME = "Michigan House"

    @property
    def source_name(self) -> str:
        return self.SOURCE_NAME

    # Scrapes the public video archive page and returns unique video records.
    async def get_new_videos(self) -> list[dict]:
        self._dedup = DeduplicationTracker()  # Reset deduplication tracker for each scrape
        videos = []
        client = await self.get_client()

        try:
            response = await fetch_with_retry(client, LISTING_URL)
            soup = BeautifulSoup(response.text, "html.parser")

            items = []
            for div in soup.find_all("div", class_="page-search-object"):
                link = div.find("a", href=True)
                if not link:
                    continue

                href = link["href"]
                if "VideoArchivePlayer?video=" not in href:
                    continue

                filename = href.split("video=")[-1]
                date_text = link.get_text(strip=True)

                items.append({
                    "filename": filename,
                    "date_text": date_text,
                })

            unseen_items = self._dedup.get_unseen_videos(items, id_key="filename")

            for item in unseen_items:
                filename = item["filename"]
                date_text = item["date_text"]
                download_url = f"{DOWNLOAD_BASE}/{filename}"

                # item={} is deliberate: House's HTML never exposes duration/
                # size, so duration_secs comes back None (should_transcribe()
                # in transcriber.py already treats that as "don't exclude").
                metadata = MetadataExtractor.normalize_portal_metadata(
                    item={},
                    source_name=self.SOURCE_NAME,
                    title=filename.replace(".mp4", ""),
                    portal_id=filename.replace(".mp4", ""),
                    date_text=date_text,
                    filename=filename,
                )

                video_record = MetadataExtractor.build_video_record(
                    video_url=download_url,
                    metadata=metadata,
                )

                videos.append(video_record)
                logger.info(f"[{self.SOURCE_NAME}] Found: {filename} - {date_text}")

        except Exception as e:
            # Surface parsing failures but don't crash the whole scraper
            logger.warning(f"[{self.SOURCE_NAME}] Scrape failed: {e}")
        finally:
            await self.close_client()
        logger.info(f"[{self.source_name}] Total unique videos found: {len(videos)}")
        return videos
