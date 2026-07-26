# Shared metadata extraction/normalization/enrichment logic used by detectors.

from typing import Dict, Any, Optional


# Extracts and normalizes metadata from video sources.
class MetadataExtractor:

    @staticmethod
    def safe_get(obj: Dict[str, Any], key: str, default: Any = None) -> Any:
        return obj.get(key) if obj else default

    # Returns {"duration_secs", "duration_mins"} parsed from raw metadata.
    @staticmethod
    def extract_duration(metadata: Dict[str, Any]) -> Dict[str, Any]:
        try:
            duration_secs = int(float(metadata.get("duration", 0) or 0))
            return {
                "duration_secs": duration_secs,
                "duration_mins": round(duration_secs / 60, 1),
            }
        except (ValueError, TypeError):
            return {"duration_secs": 0, "duration_mins": 0}

    # Returns {"size_bytes", "size_mb"} parsed from raw metadata.
    @staticmethod
    def extract_size(metadata: Dict[str, Any]) -> Dict[str, Any]:
        try:
            size_bytes = int(float(metadata.get("size", 0) or 0))
            return {
                "size_bytes": size_bytes,
                # Decimal MB (1e6), not binary MiB — matches every other
                # size calc in this codebase (hls.py, http_audio.py, vtt.py).
                "size_mb": round(size_bytes / 1_000_000, 1),
            }
        except (ValueError, TypeError):
            return {"size_bytes": 0, "size_mb": 0}

    # Builds the normalized metadata dict stored on a job (title, portal_id,
    # duration/size if present, plus any extra_fields a portal wants to keep).
    @staticmethod
    def normalize_portal_metadata(
        item: Dict[str, Any],
        source_name: str,
        title: Optional[str] = None,
        portal_id: Optional[str] = None,
        **extra_fields
    ) -> Dict[str, Any]:
        metadata = {
            "portal": source_name,
            "title": title or "untitled",
            "portal_id": portal_id or "unknown",
        }

        if "duration" in item or "metadata" in item:
            item_meta = item.get("metadata", item)
            metadata.update(MetadataExtractor.extract_duration(item_meta))
            metadata.update(MetadataExtractor.extract_size(item_meta))

        metadata.update(extra_fields)

        return metadata

    # Builds the {video_url, metadata} record a detector returns per video.
    @staticmethod
    def build_video_record(
        video_url: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "video_url": video_url,
            "metadata": metadata,
        }
