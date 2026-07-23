import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from shared.config import SCRAPE_INTERVAL_SECONDS
from shared.db.database import ping
from services.scraper.scraper import run_scrape
from services.downloader.downloader import run_downloads


async def run_pipeline():
    """Run scraper then downloader in sequence."""
    await run_scrape()
    await run_downloads()


async def main():
    await ping()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_pipeline,
        trigger="interval",
        seconds=SCRAPE_INTERVAL_SECONDS,
        id="pipeline",
        replace_existing=True,
        next_run_time=datetime.now(),
    )

    scheduler.start()
    print(f"⏰ Scheduler started — running every {SCRAPE_INTERVAL_SECONDS}s")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("Scheduler stopped.")


if __name__ == "__main__":
    asyncio.run(main())