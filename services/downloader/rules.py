# Business rules for the downloader — all decisions about HOW a job
# gets downloaded live here; change behavior by editing only this file.

from shared.media_urls import (
    CAPTION_URL_TEMPLATE,
    AUDIO_URL_TEMPLATE,
)
from shared.logging_config import get_logger

logger = get_logger(__name__)


# What should be downloaded for a single job; built by DownloadRules and
# executed by the downloader.
class DownloadPlan:

    def __init__(self):
        self.downloads = []  # list of {url, destination, strategy}

    # Adds one download action to the plan.
    def add(self, url: str, destination: str, strategy: str):
        self.downloads.append({
            "url": url,
            "destination": destination,
            "strategy": strategy,
        })

    # True when no downloads have been scheduled; the downloader treats
    # an empty plan as a signal to skip the job.
    def is_empty(self) -> bool:
        return len(self.downloads) == 0


# Decides what to download per job. Senate: captioned -> VTT only,
# uncaptioned -> audio via HLS. House: extract audio directly via FFmpeg.
# Adding a new portal: add an elif block here and in portal_registry.py.
class DownloadRules:

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
            title = metadata.get("title", "")

            # "Live Stream N" / untitled entries are per-channel slots (e.g.
            # "ch1"), not one-time recordings — confirmed via the portal's
            # getLive/infoLive API, so they're skipped rather than guessed at.
            if title.lower().startswith("live stream") or title.strip().lower() in ("", "untitled"):
                logger.info(f"[rules] Senate — skipping live-channel entry (no stable recording): {title or 'untitled'}")
                return plan

            if captioned:
                # Fast path — parsing VTT is far cheaper than running Whisper.
                vtt_dest = f"{DownloadRules.CAPTION_DIR}/{source}/{portal_id}.vtt"
                vtt_url = CAPTION_URL_TEMPLATE.format(portal_id=portal_id)
                plan.add(vtt_url, vtt_dest, "vtt")

                logger.info(f"[rules] Senate captioned — VTT only: {portal_id}")

            else:
                # No captions — fall back to HLS audio for Whisper to transcribe.
                audio_dest = f"{DownloadRules.AUDIO_DIR}/{source}/{portal_id}.mp3"
                audio_url = AUDIO_URL_TEMPLATE.format(portal_id=portal_id)
                plan.add(audio_url, audio_dest, "hls")

                logger.info(f"[rules] Senate uncaptioned — audio only: {portal_id}")

        # ── Rule: Michigan House ──────────────────────────────────────────────
        elif source == "michigan_house":
            # FFmpeg extracts audio directly from the source URL; the full
            # video is never written to disk. SSL verification is skipped
            # for House in HTTPAudioExtractStrategy (bad certs).
            filename = metadata.get("filename", f"{portal_id}.mp4")
            stem = filename[:-4] if filename.endswith(".mp4") else filename
            audio_dest = f"{DownloadRules.AUDIO_DIR}/{source}/{stem}.mp3"
            plan.add(video_url, audio_dest, "http_audio_extract")

            logger.info(f"[rules] House — extracting audio: {filename}")

        # ── Fallback: unknown source ──────────────────────────────────────────
        else:
            logger.info(f"[rules] No rule defined for source: {source} — skipping")

        return plan
