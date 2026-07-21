import httpx
from services.scraper.detectors.base import BaseDetector

BASE_URL = "https://2kbyogxrg4.execute-api.us-west-2.amazonaws.com/61b3adc8124d7d000891ca5c"

TABS = {
    "home":      "home/home",
    "live":      "home/live",
    "recent":    "home/recent",
    "playlists": "home/playlists",
    "featured":  "home/featured",
    "popular":   "home/popular",
}

class CouncilPortalDetector(BaseDetector):

    @property
    def source_name(self) -> str:
        return "michigan_senate"

    async def get_new_videos(self) -> list[dict]:
        videos = []
        seen_ids = set()

        async with httpx.AsyncClient(timeout=30) as client:
            for tab_name, tab_path in TABS.items():
                print(f"[{self.source_name}] Scraping tab: {tab_name}")
                try:
                    response = await client.get(f"{BASE_URL}/{tab_path}")
                    response.raise_for_status()
                    data = response.json()

                    items = data if isinstance(data, list) else data.get("results", [])

                    for item in items:
                        video_id = str(item.get("_id"))

                        if video_id in seen_ids:
                            continue
                        seen_ids.add(video_id)

                        if not item.get("transcoded", False):
                            print(f"[{self.source_name}] Skipping untranscoded: {video_id}")
                            continue

                        if item.get("access") != "open":
                            print(f"[{self.source_name}] Skipping restricted: {video_id}")
                            continue

                        duration = int(float(item.get("metadata", {}).get("duration", 0) or 0))
                        size = int(float(item.get("size", 0) or 0))
                        filename = item.get("metadata", {}).get("filename", "untitled")
                        original_date = item.get("original_date")
                        captioned = item.get("captioned", False)

                        videos.append({
                            "video_url": f"{BASE_URL}/video/{video_id}",
                            "metadata": {
                                "portal_id":     video_id,
                                "title":         filename,
                                "duration_secs": duration,
                                "duration_mins": round(duration / 60, 1),
                                "original_date": original_date,
                                "size_bytes":    size,
                                "size_mb":       round(size / 1_000_000, 1),
                                "captioned":     captioned,
                                "tab":           tab_name,
                                "portal":        self.source_name,
                            }
                        })

                        print(f"[{self.source_name}] Found: {filename} ({round(duration / 60, 1)} mins)")

                except Exception as e:
                    print(f"[{self.source_name}] Failed on tab {tab_name}: {e}")
                    continue

        print(f"[{self.source_name}] Total unique videos found: {len(videos)}")
        return videos