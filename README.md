chamber-scribe/
│
├── services/
│   ├── scheduler/
│   │   └── cron.py              ✅ parallel loops via asyncio.gather
│   │
│   ├── scraper/
│   │   ├── scraper.py           ✅ upsert idempotency, DuplicateKeyError safe
│   │   ├── config.py            ✅ HTTP constants
│   │   ├── http_utils.py        ✅ fetch_with_retry, exponential backoff
│   │   ├── filter_utils.py      ✅ VideoFilter, DeduplicationTracker
│   │   ├── metadata_utils.py    ✅ MetadataExtractor, normalize_portal_metadata
│   │   └── detectors/
│   │       ├── base.py          ✅ BaseDetector, HTTPDetector
│   │       ├── senate_portal.py ✅ CouncilPortalDetector, HLS URLs
│   │       └── house_portal.py  ✅ HousePortalDetector, HTML parsing
│   │
│   ├── downloader/
│   │   ├── downloader.py        ✅ batch 10, JobStatus enum, parallel gather
│   │   ├── config.py            ✅ BATCH_SIZE=10, timeouts, CloudFront URLs
│   │   ├── rules.py             ✅ DownloadPlan, business rules per source
│   │   └── strategies/
│   │       ├── base.py          ✅ BaseDownloadStrategy
│   │       ├── hls.py           ✅ FFmpeg audio-only extraction
│   │       ├── http.py          ✅ chunked HTTP download
│   │       └── vtt.py           ✅ VTT caption download
│   │
│   ├── transcriber/
│   │   ├── transcriber.py       ✅ GPU transcription, audio cleanup after done
│   │   ├── config.py            ✅ CUDA