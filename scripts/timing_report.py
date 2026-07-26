"""One-off helper: real scrape/download/transcribe timings from your own
job history, grouped by source (michigan_senate vs michigan_house).

Answers "how long does it take to scrape/download/transcribe a video?"
with actual numbers from created_at/downloaded_at/transcribed_at instead
of a guess — run this after the pipeline has processed a batch of videos.

Usage:
    python -m scripts.timing_report
"""

import asyncio
from collections import defaultdict
from statistics import mean, median

from shared.db.database import jobs_collection


def _seconds(start, end) -> float | None:
    if not start or not end:
        return None
    return (end - start).total_seconds()


async def timing_report() -> None:
    col = jobs_collection()
    cursor = col.find(
        {},
        {"source": 1, "created_at": 1, "downloaded_at": 1, "transcribed_at": 1, "status": 1},
    )
    jobs = await cursor.to_list(length=None)

    if not jobs:
        print("No jobs yet — run the pipeline first, then re-run this.")
        return

    # download_secs = created_at -> downloaded_at (queue detection -> file on disk)
    # transcribe_secs = downloaded_at -> transcribed_at (file on disk -> transcript saved)
    by_source = defaultdict(lambda: {"download_secs": [], "transcribe_secs": []})

    for job in jobs:
        source = job.get("source", "unknown")
        d = _seconds(job.get("created_at"), job.get("downloaded_at"))
        t = _seconds(job.get("downloaded_at"), job.get("transcribed_at"))
        if d is not None:
            by_source[source]["download_secs"].append(d)
        if t is not None:
            by_source[source]["transcribe_secs"].append(t)

    print(f"\n{len(jobs)} total job(s) in the database\n")

    for source, stats in by_source.items():
        print(f"-- {source} --")
        for label, values in stats.items():
            if not values:
                print(f"  {label:<16} no completed jobs yet")
                continue
            print(
                f"  {label:<16} n={len(values):<4} "
                f"mean={mean(values):>7.1f}s  median={median(values):>7.1f}s  "
                f"min={min(values):>7.1f}s  max={max(values):>7.1f}s"
            )
        print()

    print(
        "Note: 'download' covers the full scraper-queues-it -> file-on-disk\n"
        "window (includes time sitting in 'pending' between polls, since\n"
        "there's no separate 'download started' timestamp). 'transcribe'\n"
        "is downloaded_at -> transcribed_at, which is the actual processing\n"
        "time (Whisper or instant VTT parse)."
    )


if __name__ == "__main__":
    asyncio.run(timing_report())
