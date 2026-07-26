# Tuning knobs for the downloader loop and its FFmpeg/httpx calls.
BATCH_SIZE = 10          # jobs claimed per downloader_loop cycle
DOWNLOAD_TIMEOUT = 600   # 10 mins for large audio files
