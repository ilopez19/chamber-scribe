import os
from dotenv import load_dotenv
from shared.logging_config import get_logger

logger = get_logger(__name__)

# Load the configuration from the .env file
load_dotenv()
# allows us to access all the mongo DB variables and use them throughout the application
#safely
MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB_NAME = os.environ["MONGO_DB_NAME"]
SCRAPE_INTERVAL_SECONDS = int(os.environ["SCRAPE_INTERVAL_SECONDS"])

# Job-lifecycle retry ceiling — how many times the downloader or transcriber
# will retry a job at their own stage before giving up on it permanently.
# Single source of truth for downloader.py, transcriber.py, and scraper.py
# (the scraper uses it to decide when a permanently-failed job is safe to
# re-queue from scratch). Not to be confused with the HTTP-request-level
# retry configs in services/scraper/config.py or
# services/downloader/config.py, which govern retrying a single network
# call, not a job's overall attempts.
JOB_MAX_RETRIES = int(os.environ.get("JOB_MAX_RETRIES", 3))

# NOTE: don't print MONGO_URI — it can carry embedded credentials and this
# module gets imported by everything, so it would leak into every log.
logger.info(f"[config] DB: {MONGO_DB_NAME} | Scrape interval: {SCRAPE_INTERVAL_SECONDS}s")