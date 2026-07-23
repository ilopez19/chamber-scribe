"""
Business rules for the downloader.

All decisions about HOW a job should be downloaded live here.
Change download behaviour by updating this file only.
"""

from services.downloader.config import (
    CLOUDFRONT_BASE,
    CAPTION_URL_TEMPLATE,
    AUDIO_URL_TEMPLATE,
)


class DownloadPlan:
    """
    Represents what should be downloaded for a single job.
    Built by DownloadRules and executed by the downloader.
    """

    def __init__(self):
        self.downloads = []  # list of (url, destination, strategy_name)

    def add(self, url: str, destination: str, strategy: str):
        self.downloads.append({
            "url": url,
            "destination": destination,
            "strategy": strategy,
        })

    def is_empty(self) -> bool:
        return len(self.downloads) == 0


class DownloadRules:
    """
    Determines what to download for each job based on business rules.

    Rules (in priority order):
    1. If captioned → download VTT + audio backup
    2. If not captioned → download audio only
    3. Source-specific overrides can be added here per portal
    """

    AUDIO_DIR = "storage/audio"
    CAPTION_DIR = "storage/captions"

    @staticmethod
    def build_plan(job: dict) -> DownloadPlan:
        plan = DownloadPlan()

        metadata = job.get("metadata", {})
        portal_id = metadata.get("portal_id")
        source = job.get("source", "unknown")
        captioned = metadata.get("captioned", False)
        video_url = job.get("video_url", "")

        # --- Rule 1: Senate videos (HLS streams) ---
        if source == "michigan_senate" and portal_id:

            # Always download audio
            audio_dest = f"{DownloadRules.AUDIO_DIR}/{source}/{portal_id}.mp3"
            audio_url = AUDIO_URL_TEMPLATE.format(portal_id=portal_id)
            plan.add(audio_url, audio_dest, "hls")

            # If captioned, also download VTT
            if captioned:
                vtt_dest = f"{DownloadRules.CAPTION_DIR}/{source}/{portal_id}.vtt"
                vtt_url = CAPTION_URL_TEMPLATE.format(portal_id=portal_id)
                plan.add(vtt_url, vtt_dest, "vtt")

        # --- Rule 2: House videos (direct MP4) ---
        elif source == "michigan_house":
            filename = metadata.get("filename", f"{portal_id}.mp4")
            audio_dest = f"{DownloadRules.AUDIO_DIR}/{source}/{filename}.mp3"
            plan.add(video_url, audio_dest, "http_audio")

        # --- Rule 3: Unknown source fallback ---
        else:
            print(f"[rules] No rule defined for source: {source} — skipping")

        return plan