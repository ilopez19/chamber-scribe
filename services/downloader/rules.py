"""
Business rules for the downloader.

All decisions about HOW a job should be downloaded live here.
Change download behaviour by updating this file only.
"""

from services.downloader.config import (
    CAPTION_URL_TEMPLATE,
    AUDIO_URL_TEMPLATE,
)


class DownloadPlan:
    """
    Represents what should be downloaded for a single job.
    Built by DownloadRules and executed by the downloader.
    """

    def __init__(self):
        self.downloads = []  # list of {url, destination, strategy}

    def add(self, url: str, destination: str, strategy: str):
        """Add an entry describing a single download action.

        This small wrapper keeps the DownloadPlan structure consistent and is
        intentionally simple; higher-level decision logic lives in
        ``DownloadRules``.
        """
        self.downloads.append({
            "url": url,
            "destination": destination,
            "strategy": strategy,
        })

    def is_empty(self) -> bool:
        """Return True when no downloads have been scheduled.

        The downloader interprets an empty plan as a signal to skip the job.
        """
        return len(self.downloads) == 0


class DownloadRules:
    """
    Determines what to download for each job based on business rules.

    Senate rules (in priority order):
    1. If captioned=True  → download VTT only (transcriber uses VTT fast path)
                            skip audio entirely — saves GPU time + bandwidth
    2. If captioned=False → download audio only (transcriber uses Whisper)

    House rules:
    1. Download audio via HTTP

    Adding a new portal: add an elif block here and in portal_registry.py.
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

        # ── Rule: Michigan Senate ─────────────────────────────────────────────
        if source == "michigan_senate" and portal_id:

            if captioned:
                # Fast path — if captions exist we prefer the VTT route.
                # Business rationale: parsing VTT is orders of magnitude faster
                # than running Whisper on audio (saves GPU time and cost).
                vtt_dest = f"{DownloadRules.CAPTION_DIR}/{source}/{portal_id}.vtt"
                vtt_url = CAPTION_URL_TEMPLATE.format(portal_id=portal_id)
                plan.add(vtt_url, vtt_dest, "vtt")

                print(f"[rules] Senate captioned — VTT only: {portal_id}")

            else:
                # No captions — fall back to audio download so Whisper can
                # generate a transcript. We prefer HLS strategy for Senate
                # because media is served via CloudFront HLS manifests.
                audio_dest = f"{DownloadRules.AUDIO_DIR}/{source}/{portal_id}.mp3"
                audio_url = AUDIO_URL_TEMPLATE.format(portal_id=portal_id)
                plan.add(audio_url, audio_dest, "hls")

                print(f"[rules] Senate uncaptioned — audio only: {portal_id}")

        # ── Rule: Michigan House ──────────────────────────────────────────────
        elif source == "michigan_house":
            # House serves static MP4 files — download over HTTP and extract
            # audio. Note: some House URLs require skipping SSL verification,
            # handled in the HTTPDownloadStrategy initialization elsewhere.
            filename = metadata.get("filename", f"{portal_id}.mp4")
            audio_dest = f"{DownloadRules.AUDIO_DIR}/{source}/{filename}.mp3"
            plan.add(video_url, audio_dest, "http_audio")

            print(f"[rules] House — HTTP audio: {filename}")

        # ── Fallback: unknown source ──────────────────────────────────────────
        else:
            print(f"[rules] No rule defined for source: {source} — skipping")

        return plan