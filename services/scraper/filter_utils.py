# Shared filtering/deduplication helpers used by detectors.

from typing import Dict, Any, List, Set


# Centralized video filtering logic.
class VideoFilter:

    # True if video passes (required=True means only transcoded videos pass).
    @staticmethod
    def filter_by_transcoding(video: Dict[str, Any], required: bool = True) -> bool:
        if required:
            return video.get("transcoded", False)
        return True

    # True if video's access field matches required_access.
    @staticmethod
    def filter_by_access_level(video: Dict[str, Any], required_access: str = "open") -> bool:
        return video.get("access") == required_access

    # True if video's duration is at least min_seconds.
    @staticmethod
    def filter_by_duration(video: Dict[str, Any], min_seconds: float = 0) -> bool:
        try:
            metadata = video.get("metadata", {})
            duration = int(float(metadata.get("duration", 0) or 0))
            return duration >= min_seconds
        except (ValueError, TypeError):
            return False

    # True if video has the fields required for job creation.
    @staticmethod
    def is_valid_video(video: Dict[str, Any]) -> bool:
        return (
            "video_url" in video
            and video["video_url"]
            and "metadata" in video
            and isinstance(video["metadata"], dict)
        )


# Tracks seen video IDs within one scrape run to avoid duplicates.
class DeduplicationTracker:

    def __init__(self):
        self._seen: Set[str] = set()

    def is_seen(self, video_id: str) -> bool:
        return video_id in self._seen

    def mark_seen(self, video_id: str) -> None:
        self._seen.add(video_id)

    # Returns only the videos not already seen, marking them seen as it goes.
    def get_unseen_videos(self, videos: List[Dict[str, Any]], id_key: str = "_id") -> List[Dict[str, Any]]:
        unseen = []
        for video in videos:
            video_id = str(video.get(id_key))
            if not self.is_seen(video_id):
                self.mark_seen(video_id)
                unseen.append(video)
        return unseen

    def count_seen(self) -> int:
        return len(self._seen)
