import os
from dotenv import load_dotenv
from shared.logging_config import get_logger

logger = get_logger(__name__)

# Load the configuration from the .env file
load_dotenv()

MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB_NAME = os.environ["MONGO_DB_NAME"]
SCRAPE_INTERVAL_SECONDS = int(os.environ["SCRAPE_INTERVAL_SECONDS"])

# How many times the downloader/transcriber retry a job before giving up
# permanently; scraper.py uses it to decide when to re-queue a failed job.
# Not the same as the HTTP-request retry configs in scraper/config.py or
# downloader/config.py, which govern one network call, not a whole job.
JOB_MAX_RETRIES = int(os.environ.get("JOB_MAX_RETRIES", 3))

# NOTE: don't print MONGO_URI — it can carry embedded credentials and this
# module gets imported by everything, so it would leak into every log.
logger.info(f"[config] DB: {MONGO_DB_NAME} | Scrape interval: {SCRAPE_INTERVAL_SECONDS}s")