import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from shared.config import SCRAPE_INTERVAL_SECONDS
from shared.db.database import ping
from services.scraper.scraper import run_scrape

async def main():
    await ping()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_scrape,
        trigger="interval",
        seconds=SCRAPE_INTERVAL_SECONDS,
        id="scraper",
        replace_existing=True,
    )

    scheduler.start()
    print(f"⏰ Scheduler started — scraping every {SCRAPE_INTERVAL_SECONDS}s")

    await run_scrape()

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("Scheduler stopped.")

if __name__ == "__main__":
    asyncio.run(main())