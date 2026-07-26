# Tests for DownloadRules.build_plan() — the single place that decides
# HOW (or whether) a job gets downloaded, including the live-channel
# exclusion for "Live Stream N" / untitled entries that have no stable recording.

from services.downloader.rules import DownloadRules


def _senate_job(portal_id="abc123", captioned=False, title="Committee Hearing"):
    return {
        "source": "michigan_senate",
        "video_url": f"https://example.cloudfront.net/outputs/{portal_id}/Default/HLS/out.m3u8",
        "metadata": {"portal_id": portal_id, "captioned": captioned, "title": title},
    }


def _house_job(filename="AGRR-022526.mp4", video_url="https://house.mi.gov/ArchiveVideoFiles/AGRR-022526.mp4"):
    return {
        "source": "michigan_house",
        "video_url": video_url,
        "metadata": {"portal_id": "house-1", "filename": filename},
    }


class TestSenateRules:
    def test_captioned_downloads_vtt_only(self):
        plan = DownloadRules.build_plan(_senate_job(captioned=True, portal_id="p1"))
        assert len(plan.downloads) == 1
        entry = plan.downloads[0]
        assert entry["strategy"] == "vtt"
        assert entry["destination"].endswith("p1.vtt")

    def test_uncaptioned_downloads_audio_via_hls(self):
        plan = DownloadRules.build_plan(_senate_job(captioned=False, portal_id="p2"))
        assert len(plan.downloads) == 1
        entry = plan.downloads[0]
        assert entry["strategy"] == "hls"
        assert entry["destination"].endswith("p2.mp3")

    def test_live_stream_title_is_excluded(self):
        plan = DownloadRules.build_plan(_senate_job(title="Live Stream 2", captioned=True))
        assert plan.is_empty()

    def test_live_stream_title_is_case_insensitive(self):
        plan = DownloadRules.build_plan(_senate_job(title="LIVE STREAM 7"))
        assert plan.is_empty()

    def test_untitled_entry_is_excluded(self):
        plan = DownloadRules.build_plan(_senate_job(title="untitled"))
        assert plan.is_empty()

    def test_missing_title_is_excluded(self):
        job = _senate_job(title="")
        plan = DownloadRules.build_plan(job)
        assert plan.is_empty()

    def test_normal_title_is_not_excluded(self):
        plan = DownloadRules.build_plan(_senate_job(title="Appropriations 26-07-01"))
        assert not plan.is_empty()

    def test_missing_portal_id_produces_no_plan(self):
        job = _senate_job()
        job["metadata"]["portal_id"] = None
        plan = DownloadRules.build_plan(job)
        assert plan.is_empty()


class TestHouseRules:
    def test_extracts_audio_from_video_url(self):
        plan = DownloadRules.build_plan(_house_job())
        assert len(plan.downloads) == 1
        entry = plan.downloads[0]
        assert entry["strategy"] == "http_audio_extract"
        assert entry["url"] == "https://house.mi.gov/ArchiveVideoFiles/AGRR-022526.mp4"

    def test_mp4_extension_is_stripped_not_doubled(self):
        plan = DownloadRules.build_plan(_house_job(filename="HAGRI-022626.mp4"))
        dest = plan.downloads[0]["destination"]
        assert dest.endswith("HAGRI-022626.mp3")
        assert ".mp4" not in dest

    def test_non_mp4_filename_is_kept_as_is(self):
        plan = DownloadRules.build_plan(_house_job(filename="weird-name"))
        dest = plan.downloads[0]["destination"]
        assert dest.endswith("weird-name.mp3")


class TestUnknownSource:
    def test_unknown_source_produces_no_plan(self):
        job = {"source": "some_other_state", "video_url": "https://example.com/x", "metadata": {"portal_id": "1"}}
        plan = DownloadRules.build_plan(job)
        assert plan.is_empty()
