# Entry point (`python main.py` or run.bat): runs the scraper, downloader,
# and transcriber as 3 independent loops in one process, each heartbeating
# to Mongo so /health can report liveness. The REST API is separate —
# start it with `uvicorn api.main:app`.

import asyncio
import time

from shared.config import SCRAPE_INTERVAL_SECONDS
from shared.db.database import ping, heartbeat
from services.scraper.scraper import run_scrape
from services.downloader.downloader import run_downloads
from services.transcriber.transcriber import run_transcriptions
from shared.logging_config import get_logger

logger = get_logger(__name__)

DOWNLOADER_INTERVAL_SECONDS = 30
TRANSCRIBER_INTERVAL_SECONDS = 30


# Runs every SCRAPE_INTERVAL_SECONDS — checks the portals for new videos.
async def scraper_loop():
    while True:
        ok = True
        try:
            await run_scrape()
        except Exception as e:
            logger.error(f"[scraper_loop] Error: {e}")
            ok = False
        # Heartbeat runs whether or not the cycle succeeded — it means
        # "this loop is alive," not "the last cycle worked." `ok` carries
        # success/failure separately for /health to surface.
        await heartbeat("scraper_loop", {"ok": ok, "interval_seconds": SCRAPE_INTERVAL_SECONDS})
        await asyncio.sleep(SCRAPE_INTERVAL_SECONDS)


# Runs every 30s — downloads audio/captions for pending jobs.
async def downloader_loop():
    while True:
        ok = True
        try:
            await run_downloads()
        except Exception as e:
            logger.error(f"[downloader_loop] Error: {e}")
            ok = False
        await heartbeat("downloader_loop", {"ok": ok, "interval_seconds": DOWNLOADER_INTERVAL_SECONDS})
        await asyncio.sleep(DOWNLOADER_INTERVAL_SECONDS)


# Runs every 30s — transcribes downloaded jobs.
async def transcriber_loop():
    while True:
        ok = True
        try:
            await run_transcriptions()
        except Exception as e:
            logger.error(f"[transcriber_loop] Error: {e}")
            ok = False
        await heartbeat("transcriber_loop", {"ok": ok, "interval_seconds": TRANSCRIBER_INTERVAL_SECONDS})
        await asyncio.sleep(TRANSCRIBER_INTERVAL_SECONDS)


async def main():
    await ping()
    logger.info("Starting all services in parallel...")
    logger.info(f"   Scraper:     every {SCRAPE_INTERVAL_SECONDS}s")
    logger.info(f"   Downloader:  every {DOWNLOADER_INTERVAL_SECONDS}s")
    logger.info(f"   Transcriber: every {TRANSCRIBER_INTERVAL_SECONDS}s")

    await asyncio.gather(
        scraper_loop(),
        downloader_loop(),
        transcriber_loop(),
    )


# Restarts main() with exponential backoff if it ever exits from an
# unhandled crash, instead of leaving the process dead until someone
# notices. Backoff resets after a stable run so one early crash doesn't
# slow down every future restart.
def run_forever():
    backoff = 5
    max_backoff = 300

    while True:
        started_at = time.monotonic()
        try:
            asyncio.run(main())
            logger.error("[main] Pipeline exited unexpectedly (loops should run forever) - restarting.")
        except KeyboardInterrupt:
            logger.info("[main] Stopped by user.")
            break
        except Exception as e:
            logger.error(f"[main] Pipeline crashed: {e!r}")

        if time.monotonic() - started_at > 60:
            backoff = 5

        logger.info(f"[main] Restarting in {backoff}s...")
        time.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


if __name__ == "__main__":
    run_forever()
