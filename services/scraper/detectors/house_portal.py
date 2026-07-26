import warnings
from bs4 import BeautifulSoup
from services.scraper.detectors.base import HTTPDetector
from services.scraper.http_utils import fetch_with_retry
from services.scraper.filter_utils import DeduplicationTracker
from services.scraper.metadata_utils import MetadataExtractor
from shared.logging_config import get_logger

logger = get_logger(__name__)

# The House site has certificate problems; ignore the related warnings to
# avoid noisy logs. The HTTP strategy explicitly disables verification when
# communicating with this host.
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

BASE_URL = "https://house.mi.gov"
LISTING_URL = f"{BASE_URL}/VideoArchive"
DOWNLOAD_BASE = f"{BASE_URL}/ArchiveVideoFiles"


class HousePortalDetector(HTTPDetector):

    def __init__(self):
        # Server uses invalid certs; detector and strategies handle verification
        super().__init__(timeout=30, verify=False)
        self._dedup = DeduplicationTracker()

    @property
    def source_name(self) -> str:
        return "michigan_house"

    async def get_new_videos(self) -> list[dict]:
        """Scrape the public video archive page and return unique video records.

        The detector parses HTML listings for video links, extracts filenames
        used to build download URLs, and normalizes metadata. Deduplication is
        reset per-run so repeats across runs are handled by the jobs collection
        uniqueness.
        """
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

                # item={} is deliberate, not a stub left unfinished: the House
                # archive page (unlike the Senate's JSON API) never exposes
                # duration or file size anywhere in its HTML — there's no
                # field to read them from. That means duration_secs comes
                # back as None for every House job (see extract_duration()
                # in metadata_utils.py), and should_transcribe() in
                # transcriber.py already special-cases None so House videos
                # aren't silently excluded by the duration-too-short rule.
                # A real fix would require a second request per video to a
                # detail page, if one exists — not attempted here.
                metadata = MetadataExtractor.normalize_portal_metadata(
                    item={},
                    source_name=self.source_name,
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
                logger.info(f"[{self.source_name}] Found: {filename} — {date_text}")

        except Exception as e:
            # Surface parsing failures but don't crash the whole scraper
            logger.warning(f"[{self.source_name}] Scrape failed: {e}")
        finally:
            await self.close_client()
        logger.info(f"[{self.source_name}] Total unique videos found: {len(videos)}")
        return videos