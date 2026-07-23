"""
Common filtering and deduplication logic for detectors.

Provides:
- Video filtering (transcoding, access control, etc.)
- Deduplication tracking
- Video validation
"""

from typing import Dict, Any, List, Set


class VideoFilter:
    """Centralized video filtering logic."""

    @staticmethod
    def filter_by_transcoding(video: Dict[str, Any], required: bool = True) -> bool:
        """
        Filter video by transcoding status.

        Args:
            video: Video metadata dict
            required: If True, only accept transcoded videos

        Returns:
            True if video passes filter
        """
        if required:
            return video.get("transcoded", False)
        return True

    @staticmethod
    def filter_by_access_level(video: Dict[str, Any], required_access: str = "open") -> bool:
        """
        Filter video by access level.

        Args:
            video: Video metadata dict
            required_access: Required access level (e.g., "open", "public")

        Returns:
            True if video passes filter
        """
        return video.get("access") == required_access

    @staticmethod
    def filter_by_duration(video: Dict[str, Any], min_seconds: float = 0) -> bool:
        """
        Filter video by duration.

        Args:
            video: Video metadata dict
            min_seconds: Minimum duration in seconds

        Returns:
            True if video duration >= min_seconds
        """
        try:
            metadata = video.get("metadata", {})
            duration = int(float(metadata.get("duration", 0) or 0))
            return duration >= min_seconds
        except (ValueError, TypeError):
            return False

    @staticmethod
    def is_valid_video(video: Dict[str, Any]) -> bool:
        """
        Check if video has required fields for job creation.

        Args:
            video: Video dict to validate

        Returns:
            True if video is valid
        """
        return (
            "video_url" in video
            and video["video_url"]
            and "metadata" in video
            and isinstance(video["metadata"], dict)
        )


class DeduplicationTracker:
    """Track seen videos to avoid duplicates."""

    def __init__(self):
        """Initialize tracker."""
        self._seen: Set[str] = set()

    def is_seen(self, video_id: str) -> bool:
        """Check if video ID has been seen."""
        return video_id in self._seen

    def mark_seen(self, video_id: str) -> None:
        """Mark video ID as seen."""
        self._seen.add(video_id)

    def get_unseen_videos(self, videos: List[Dict[str, Any]], id_key: str = "_id") -> List[Dict[str, Any]]:
        """
        Filter videos to only unseen ones and mark them as seen.

        Args:
            videos: List of video dicts
            id_key: Key in each video dict that identifies it

        Returns:
            List of videos not previously seen
        """
        unseen = []
        for video in videos:
            video_id = str(video.get(id_key))
            if not self.is_seen(video_id):
                self.mark_seen(video_id)
                unseen.append(video)
        return unseen

    def count_seen(self) -> int:
        """Return number of unique videos seen."""
        return len(self._seen)

