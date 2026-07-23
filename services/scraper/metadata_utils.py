"""
Common metadata enrichment and normalization logic.

Provides:
- Extracting metadata from raw responses
- Normalizing metadata fields
- Enriching with computed fields (e.g., duration in minutes, size in MB)
"""

from typing import Dict, Any, Optional


class MetadataExtractor:
    """Extract and normalize metadata from video sources."""

    @staticmethod
    def safe_get(obj: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Safely get nested value with fallback."""
        return obj.get(key) if obj else default

    @staticmethod
    def extract_duration(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and normalize duration fields.

        Args:
            metadata: Raw metadata dict

        Returns:
            Dict with 'duration_secs' and 'duration_mins' keys
        """
        try:
            duration_secs = int(float(metadata.get("duration", 0) or 0))
            return {
                "duration_secs": duration_secs,
                "duration_mins": round(duration_secs / 60, 1),
            }
        except (ValueError, TypeError):
            return {"duration_secs": 0, "duration_mins": 0}

    @staticmethod
    def extract_size(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and normalize file size fields.

        Args:
            metadata: Raw metadata dict

        Returns:
            Dict with 'size_bytes' and 'size_mb' keys
        """
        try:
            size_bytes = int(float(metadata.get("size", 0) or 0))
            return {
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / 1_000_000, 1),
            }
        except (ValueError, TypeError):
            return {"size_bytes": 0, "size_mb": 0}

    @staticmethod
    def normalize_portal_metadata(
        item: Dict[str, Any],
        source_name: str,
        title: Optional[str] = None,
        portal_id: Optional[str] = None,
        **extra_fields
    ) -> Dict[str, Any]:
        """
        Normalize metadata for a portal video.

        Args:
            item: Raw item from API/HTML
            source_name: Name of the portal/source
            title: Video title
            portal_id: Unique ID in portal
            **extra_fields: Additional metadata fields

        Returns:
            Normalized metadata dict
        """
        metadata = {
            "portal": source_name,
            "title": title or "untitled",
            "portal_id": portal_id or "unknown",
        }

        # Add extracted fields (duration, size)
        if "duration" in item or "metadata" in item:
            item_meta = item.get("metadata", item)
            metadata.update(MetadataExtractor.extract_duration(item_meta))
            metadata.update(MetadataExtractor.extract_size(item_meta))

        # Add extra fields
        metadata.update(extra_fields)

        return metadata

    @staticmethod
    def build_video_record(
        video_url: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build a complete video record for job creation.

        Args:
            video_url: Download URL
            metadata: Enriched metadata dict

        Returns:
            Complete video record dict
        """
        return {
            "video_url": video_url,
            "metadata": metadata,
        }

