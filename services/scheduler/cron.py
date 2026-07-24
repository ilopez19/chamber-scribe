import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from shared.config import SCRAPE_INTERVAL_SECONDS
from shared.db.database import ping
from services.scraper.scraper import run_scrape
from services.downloader.downloader import run_downloads
from services.transcriber.transcriber import run_transcriptions

async def scraper_loop():
    """Runs every SCRAPE_INTERVAL_SECONDS."""
    while True:
        try:
            # function pulls the jobs you have into a collection
            await run_scrape()
        except Exception as e:
            print(f"[scraper_loop] Error: {e}")
        await asyncio.sleep(SCRAPE_INTERVAL_SECONDS)


async def downloader_loop():
    """Runs continuously — checks for pending jobs every 30 seconds."""
    while True:
        try:
            await run_downloads()
        except Exception as e:
            print(f"[downloader_loop] Error: {e}")
        await asyncio.sleep(30)


async def transcriber_loop():
    """Runs continuously — checks for downloaded jobs every 30 seconds."""
    while True:
        try:
            await run_transcriptions()
        except Exception as e:
            print(f"[transcriber_loop] Error: {e}")
        await asyncio.sleep(30)


async def main():
    await ping()
    print(f"⏰ Starting all services in parallel...")
    print(f"   Scraper:     every {SCRAPE_INTERVAL_SECONDS}s")
    print(f"   Downloader:  every 30s")
    print(f"   Transcriber: every 30s")

    await asyncio.gather(
        scraper_loop(),
        downloader_loop(),
        transcriber_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())