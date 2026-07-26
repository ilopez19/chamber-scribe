"""
Business rules for the downloader.

All decisions about HOW a job should be downloaded live here.
Change download behaviour by updating this file only.
"""

from services.downloader.config import (
    CAPTION_URL_TEMPLATE,
    AUDIO_URL_TEMPLATE,
)
from shared.logging_config import get_logger

logger = get_logger(__name__)


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
    1. Extract audio directly from the HTTP video URL via FFmpeg — the raw
       video is never written to disk, only the extracted audio track.

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
            title = metadata.get("title", "")

            # "Live Stream N" entries (and, it turns out, entries with no
            # title at all — metadata_utils defaults a missing filename to
            # "untitled") are per-channel slots (e.g. "ch1", "ch2"), not
            # one-time recordings — confirmed via the portal's own
            # getLive/infoLive API and by requesting the channel manifest
            # directly (vod_clients/misenate/live/ch1/video.m3u8 returns a
            # live, continuously-updating stream with no video ID in the
            # URL at all). Our normal on-demand URL template below doesn't
            # apply to them — every properly-titled job has downloaded
            # successfully from it, and every untitled one has failed
            # against it, which is why missing title is being used as the
            # signal here. Treating one as a normal video would risk
            # silently never re-checking a channel that gets reused later
            # with different content, so these are skipped rather than
            # guessed at.
            if title.lower().startswith("live stream") or title.strip().lower() in ("", "untitled"):
                logger.info(f"[rules] Senate — skipping live-channel entry (no stable recording): {title or 'untitled'}")
                return plan

            if captioned:
                # Fast path — if captions exist we prefer the VTT route.
                # Business rationale: parsing VTT is orders of magnitude faster
                # than running Whisper on audio (saves GPU time and cost).
                vtt_dest = f"{DownloadRules.CAPTION_DIR}/{source}/{portal_id}.vtt"
                vtt_url = CAPTION_URL_TEMPLATE.format(portal_id=portal_id)
                plan.add(vtt_url, vtt_dest, "vtt")

                logger.info(f"[rules] Senate captioned — VTT only: {portal_id}")

            else:
                # No captions — fall back to audio download so Whisper can
                # generate a transcript. We prefer HLS strategy for Senate
                # because media is served via CloudFront HLS manifests.
                audio_dest = f"{DownloadRules.AUDIO_DIR}/{source}/{portal_id}.mp3"
                audio_url = AUDIO_URL_TEMPLATE.format(portal_id=portal_id)
                plan.add(audio_url, audio_dest, "hls")

                logger.info(f"[rules] Senate uncaptioned — audio only: {portal_id}")

        # ── Rule: Michigan House ──────────────────────────────────────────────
        elif source == "michigan_house":
            # House serves static MP4 files. FFmpeg extracts the audio
            # directly from the source URL — the full video is never
            # downloaded to disk. Note: House URLs require skipping SSL
            # verification, handled in HTTPAudioExtractStrategy elsewhere.
            filename = metadata.get("filename", f"{portal_id}.mp4")
            stem = filename[:-4] if filename.endswith(".mp4") else filename
            audio_dest = f"{DownloadRules.AUDIO_DIR}/{source}/{stem}.mp3"
            plan.add(video_url, audio_dest, "http_audio_extract")

            logger.info(f"[rules] House — extracting audio: {filename}")

        # ── Fallback: unknown source ──────────────────────────────────────────
        else:
            logger.info(f"[rules] No rule defined for source: {source} — skipping")

        return plan