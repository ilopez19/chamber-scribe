"""Entry point — run this to start the pipeline: `python main.py` (or `run.bat`).

Starts the scraper, downloader, and transcriber as three independent loops
running concurrently in one process. Each loop catches its own errors so one
stage crashing doesn't take down the others, and each writes a heartbeat to
Mongo every cycle so the API's /health endpoint can report on this process's
liveness even though it's a separate process from the API. The whole thing
runs under a restart-with-backoff wrapper so an unhandled crash (anything
that gets past the loops' own try/excepts) doesn't leave the process dead
until someone notices and restarts it by hand.

This does NOT start the REST API — that's a separate process, started with:
    uvicorn api.main:app --reload
"""

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


async def scraper_loop():
    """Runs every SCRAPE_INTERVAL_SECONDS — checks the portals for new videos."""
    while True:
        ok = True
        try:
            await run_scrape()
        except Exception as e:
            logger.error(f"[scraper_loop] Error: {e}")
            ok = False
        # Heartbeat unconditionally (success or not) — it reports "this
        # loop is still alive and cycling," not "the last cycle succeeded."
        # A loop that's erroring every cycle but still retrying should
        # show as alive, not dead; `ok` carries the success/failure detail
        # separately for /health to surface.
        await heartbeat("scraper_loop", {"ok": ok, "interval_seconds": SCRAPE_INTERVAL_SECONDS})
        await asyncio.sleep(SCRAPE_INTERVAL_SECONDS)


async def downloader_loop():
    """Runs every 30s — downloads audio/captions for pending jobs."""
    while True:
        ok = True
        try:
            await run_downloads()
        except Exception as e:
            logger.error(f"[downloader_loop] Error: {e}")
            ok = False
        await heartbeat("downloader_loop", {"ok": ok, "interval_seconds": DOWNLOADER_INTERVAL_SECONDS})
        await asyncio.sleep(DOWNLOADER_INTERVAL_SECONDS)


async def transcriber_loop():
    """Runs every 30s — transcribes downloaded jobs."""
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


def run_forever():
    """Keep the pipeline alive across unhandled crashes.

    main() should only ever exit if something propagates past all three
    loops' own try/excepts — an actual bug, an OOM, a corrupted event
    loop, etc. Rather than letting the whole process die and stay dead
    until a human notices, this catches that, logs it, waits with
    exponential backoff, and starts over. asyncio.run() tears down and
    rebuilds the event loop each call, and shared.db.database already
    reconnects cleanly whenever the running loop changes (see
    get_client()'s loop-tracking guard), so a fresh run() is a clean
    restart rather than a half-broken one.

    Backoff resets after a reasonably long stable run, so one old crash
    early on doesn't leave every future restart waiting the full 5
    minutes even after the system's been fine for hours.
    """
    backoff = 5
    max_backoff = 300

    while True:
        started_at = time.monotonic()
        try:
            asyncio.run(main())
            logger.error("[main] Pipeline exited unexpectedly (loops should run forever) — restarting.")
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
