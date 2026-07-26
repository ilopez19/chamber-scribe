# Where Senate video files live on CloudFront once a portal_id is known.
# Single source of truth for both senate_portal.py (stores this as
# video_url for dedup) and downloader/rules.py (builds the real download
# URL from it) — they used to each hardcode their own copy and had
# already drifted out of sync before this file existed.

CLOUDFRONT_BASE = "https://dlttx48mxf9m3.cloudfront.net"
CAPTION_URL_TEMPLATE = f"{CLOUDFRONT_BASE}/captions/{{portal_id}}.vtt"
AUDIO_URL_TEMPLATE = f"{CLOUDFRONT_BASE}/outputs/{{portal_id}}/Default/HLS/out.m3u8"
