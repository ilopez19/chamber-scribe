# Portal registry — the single place defining each portal's type,
# validation rules, retry config, and alert thresholds. Adding a new
# portal = one entry in PORTAL_REGISTRY, no other files need to change.

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# How a detector should fetch/parse a portal's content.
class PortalType(str, Enum):
    JSON_API      = "json_api"       # Returns structured JSON — e.g. Michigan Senate
    HTML_PAGE     = "html_page"      # Static HTML that needs parsing — e.g. Michigan House
    AUTH_REQUIRED = "auth_required"  # Requires login before scraping
    PLAYER_PAGE   = "player_page"    # Needs Playwright to render JS before scraping


# Business rules for one portal — validation, retry, and alert settings.
@dataclass
class PortalConfig:

    # Identity
    source_name: str
    display_name: str
    portal_type: PortalType

    # Validation — added to database
    min_videos_expected: int = 1
    required_metadata_fields: list = field(default_factory=lambda: ["title", "portal_id"])

    # URL and response validation
    expected_url_pattern: str = ""        # regex the video URL must match

    # catches CDN/URL structure changes
    expected_response_type: str = "json"  # "json" or "html"
    # catches JS rendering changes

    # Rate limiting
    min_scrape_interval_seconds: int = 0  # don't scrape faster than this
    # prevents portal rate limiting

    # Seasonal thresholds
    seasonal_min_videos: dict = field(    # lower threshold during recess
        default_factory=dict              # e.g. {"july": 0, "august": 0}
    )
    alert_on_zero_videos: bool = True     # False for portals that go quiet

    # Retry config
    max_retries: int = 3
    retry_delay_seconds: int = 30

    # Alert thresholds
    alert_after_failures: int = 3
    alert_email: Optional[str] = None

    # Notes for developers adding/maintaining this portal
    notes: str = ""


# ─── Registry ────────────────────────────────────────────────────────────────
# Add every portal here. source_name must match detector.source_name exactly.

PORTAL_REGISTRY: dict[str, PortalConfig] = {

    "michigan_senate": PortalConfig(
        source_name="michigan_senate",
        display_name="Michigan Senate Video Portal",
        portal_type=PortalType.JSON_API,
        min_videos_expected=5,
        required_metadata_fields=["title", "portal_id", "original_date", "duration_secs"],
        expected_url_pattern=r"cloudfront\.net/outputs/.+/HLS/out\.m3u8",
        expected_response_type="json",
        min_scrape_interval_seconds=60,
        seasonal_min_videos={"july": 2, "august": 0},
        alert_on_zero_videos=False,
        max_retries=3,
        retry_delay_seconds=30,
        alert_after_failures=3,
        notes="CloudFront CDN for HLS streams; video listing is a single "
              "paginated POST endpoint (see senate_portal.py — the Senate "
              "has changed this before). Captioned videos have a matching "
              ".vtt on CloudFront.",
    ),

    "michigan_house": PortalConfig(
        source_name="michigan_house",
        display_name="Michigan House Video Archive",
        portal_type=PortalType.HTML_PAGE,
        min_videos_expected=10,
        required_metadata_fields=["title", "portal_id", "filename"],
        expected_url_pattern=r"house\.mi\.gov/ArchiveVideoFiles/.+\.mp4",
        expected_response_type="html",
        min_scrape_interval_seconds=300,
        seasonal_min_videos={"july": 5, "august": 0},
        alert_on_zero_videos=True,
        max_retries=3,
        retry_delay_seconds=30,
        alert_after_failures=3,
        notes="Static HTML page at house.mi.gov/VideoArchive. "
              "SSL verification disabled — site has cert issues.",
    ),

    # ── Template for future portals ──────────────────────────────────────────
    # Copy this block when adding a new portal.
    #
    # "new_portal_source_name": PortalConfig(
    #     source_name="new_portal_source_name",
    #     display_name="Human Readable Portal Name",
    #     portal_type=PortalType.HTML_PAGE,   # or JSON_API, AUTH_REQUIRED, PLAYER_PAGE
    #     min_videos_expected=1,
    #     required_metadata_fields=["title", "portal_id"],
    #     max_retries=3,
    #     retry_delay_seconds=30,
    #     alert_after_failures=3,
    #     notes="What is this portal, where are the videos, any quirks?",
    # ),
}


# Returns the PortalConfig for source_name, or None if unknown.
def get_portal_config(source_name: str) -> Optional[PortalConfig]:
    return PORTAL_REGISTRY.get(source_name)


# Validates scraped videos against a portal's rules: any videos at all,
# minimum count (with seasonal override), required fields present, and
# URL pattern match. Returns (is_valid, reason) — reason is "" if valid.
def validate_videos(videos: list[dict], config: PortalConfig) -> tuple[bool, str]:
    import re
    from datetime import datetime

    # Check 1 — any videos at all
    if not videos:
        # Some portals legitimately publish zero videos during recess — allow
        # silencing of alerts via the config flag so we don't spam operators.
        if not config.alert_on_zero_videos:
            return True, ""
        return False, "No videos returned"

    # Check 2 — minimum count with seasonal override
    current_month = datetime.now().strftime("%B").lower()  # e.g. "july"
    min_expected = config.seasonal_min_videos.get(
        current_month,
        config.min_videos_expected
    )

    if len(videos) < min_expected:
        return False, (
            f"Only {len(videos)} videos found, expected at least "
            f"{min_expected} (month={current_month})"
        )

    # Check 3 — required metadata fields on every video
    for video in videos:
        metadata = video.get("metadata", {})
        missing = [
            f for f in config.required_metadata_fields
            if not metadata.get(f)
        ]
        if missing:
            # Missing core fields usually means the portal's data shape
            # changed (or the detector has a bug) — fail loudly.
            return False, (
                f"Video missing required fields: {missing} "
                f"(url={video.get('video_url', 'unknown')})"
            )

    # Check 4 — URL pattern validation
    if config.expected_url_pattern:
        pattern = re.compile(config.expected_url_pattern)
        for video in videos:
            url = video.get("video_url", "")
            if not pattern.search(url):
                # Usually means the CDN/storage layout changed — surface it
                # before it causes large-scale download failures.
                return False, (
                    f"Video URL does not match expected pattern "
                    f"'{config.expected_url_pattern}': {url}"
                )

    return True, ""
