BATCH_SIZE = 3
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_MAX_RETRIES = 3
DOWNLOAD_RETRY_DELAY = 5
DOWNLOAD_TIMEOUT = 600  # 10 mins for large audio files

CLOUDFRONT_BASE = "https://dlttx48mxf9m3.cloudfront.net"
CAPTION_URL_TEMPLATE = f"{CLOUDFRONT_BASE}/captions/{{portal_id}}.vtt"
AUDIO_URL_TEMPLATE = f"{CLOUDFRONT_BASE}/outputs/{{portal_id}}/Default/HLS/out.m3u8"