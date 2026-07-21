import warnings
import httpx
from bs4 import BeautifulSoup
from services.scraper.detectors.base import BaseDetector

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

BASE_URL = "https://house.mi.gov"
LISTING_URL = f"{BASE_URL}/VideoArchive"
DOWNLOAD_BASE = f"{BASE_URL}/ArchiveVideoFiles"

class HousePortalDetector(BaseDetector):

    @property
    def source_name(self) -> str:
        return "michigan_house"

    async def get_new_videos(self) -> list[dict]:
        videos = []

        try:
            async with httpx.AsyncClient(timeout=30, verify=False) as client:
                response = await client.get(LISTING_URL)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")

                for div in soup.find_all("div", class_="page-search-object"):
                    link = div.find("a", href=True)
                    if not link:
                        continue

                    href = link["href"]
                    if "VideoArchivePlayer?video=" not in href:
                        continue

                    filename = href.split("video=")[-1]
                    date_text = link.get_text(strip=True)
                    download_url = f"{DOWNLOAD_BASE}/{filename}"

                    videos.append({
                        "video_url": download_url,
                        "metadata": {
                            "portal_id": filename.replace(".mp4", ""),
                            "title":     filename.replace(".mp4", ""),
                            "date_text": date_text,
                            "filename":  filename,
                            "portal":    self.source_name,
                        }
                    })

                    print(f"[{self.source_name}] Found: {filename} — {date_text}")

        except Exception as e:
            print(f"[{self.source_name}] Scrape failed: {e}")

        print(f"[{self.source_name}] Total videos found: {len(videos)}")
        return videos