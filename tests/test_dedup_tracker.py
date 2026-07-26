# Tests for DeduplicationTracker — prevents a video appearing in multiple
# portal tabs (e.g. Senate's home/live/recent/playlists) from being
# counted or queued more than once in a single scrape run.

from services.scraper.filter_utils import DeduplicationTracker


def test_first_occurrence_is_unseen():
    tracker = DeduplicationTracker()
    videos = [{"_id": "abc"}]
    assert tracker.get_unseen_videos(videos) == videos


def test_duplicate_across_calls_is_filtered_out():
    tracker = DeduplicationTracker()
    tracker.get_unseen_videos([{"_id": "abc"}])
    # Same ID appears again, as if found in a second tab.
    result = tracker.get_unseen_videos([{"_id": "abc"}])
    assert result == []


def test_duplicate_within_a_single_call_is_filtered_out():
    tracker = DeduplicationTracker()
    videos = [{"_id": "abc"}, {"_id": "abc"}, {"_id": "def"}]
    result = tracker.get_unseen_videos(videos)
    assert [v["_id"] for v in result] == ["abc", "def"]


def test_custom_id_key_is_respected():
    tracker = DeduplicationTracker()
    videos = [{"portal_id": "xyz"}]
    result = tracker.get_unseen_videos(videos, id_key="portal_id")
    assert result == videos


def test_count_seen_tracks_unique_ids_only():
    tracker = DeduplicationTracker()
    tracker.get_unseen_videos([{"_id": "a"}, {"_id": "b"}, {"_id": "a"}])
    assert tracker.count_seen() == 2


def test_is_seen_reflects_marked_ids():
    tracker = DeduplicationTracker()
    assert tracker.is_seen("abc") is False
    tracker.mark_seen("abc")
    assert tracker.is_seen("abc") is True
