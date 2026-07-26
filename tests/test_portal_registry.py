# Tests for validate_videos() — a diagnostic check, not a gate; scraper.py
# only alerts on a validation failure, it never discards the videos.

from datetime import datetime

from services.scraper.portal_registry import PortalConfig, PortalType, validate_videos


def _config(**overrides) -> PortalConfig:
    defaults = dict(
        source_name="test_portal",
        display_name="Test Portal",
        portal_type=PortalType.JSON_API,
        min_videos_expected=1,
        required_metadata_fields=["title", "portal_id"],
        expected_url_pattern="",
        alert_on_zero_videos=True,
        seasonal_min_videos={},
    )
    defaults.update(overrides)
    return PortalConfig(**defaults)


def _video(title="Hearing", portal_id="1", url="https://example.com/1.m3u8"):
    return {"video_url": url, "metadata": {"title": title, "portal_id": portal_id}}


def test_empty_result_fails_by_default():
    is_valid, reason = validate_videos([], _config())
    assert is_valid is False
    assert "No videos" in reason


def test_empty_result_is_allowed_when_configured():
    # Some portals legitimately go quiet during recess.
    is_valid, reason = validate_videos([], _config(alert_on_zero_videos=False))
    assert is_valid is True
    assert reason == ""


def test_below_minimum_count_fails():
    is_valid, reason = validate_videos([_video()], _config(min_videos_expected=5))
    assert is_valid is False
    assert "expected at least" in reason


def test_meets_minimum_count_passes():
    videos = [_video(portal_id=str(i)) for i in range(3)]
    is_valid, _ = validate_videos(videos, _config(min_videos_expected=3))
    assert is_valid is True


def test_seasonal_override_lowers_the_bar_for_the_current_month():
    current_month = datetime.now().strftime("%B").lower()
    config = _config(min_videos_expected=100, seasonal_min_videos={current_month: 0})
    # Without the override, 1 video would fail against a minimum of 100.
    is_valid, _ = validate_videos([_video()], config)
    assert is_valid is True


def test_missing_required_field_fails():
    video = {"video_url": "https://example.com/1", "metadata": {"title": "Hearing"}}  # no portal_id
    is_valid, reason = validate_videos([video], _config(min_videos_expected=1))
    assert is_valid is False
    assert "missing required fields" in reason.lower()


def test_url_not_matching_pattern_fails():
    config = _config(expected_url_pattern=r"cloudfront\.net/outputs/.+\.m3u8")
    video = _video(url="https://totally-different-host.example/video.mp4")
    is_valid, reason = validate_videos([video], config)
    assert is_valid is False
    assert "does not match" in reason.lower()


def test_url_matching_pattern_passes():
    config = _config(expected_url_pattern=r"cloudfront\.net/outputs/.+\.m3u8")
    video = _video(url="https://dlttx48mxf9m3.cloudfront.net/outputs/abc/Default/HLS/out.m3u8")
    is_valid, reason = validate_videos([video], config)
    assert is_valid is True
    assert reason == ""
