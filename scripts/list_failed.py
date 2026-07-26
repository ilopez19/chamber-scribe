"""One-off helper: print failed jobs grouped by failure reason, so patterns
("35 of your 41 failures are the same known issue") are visible without
scrolling through jobs one at a time.

Usage:
    python -m scripts.list_failed
    python -m scripts.list_failed 30      # show more individual rows
"""

import asyncio
import sys
from collections import Counter

from shared.db.database import jobs_collection


async def list_failed(limit: int) -> None:
    col = jobs_collection()
    cursor = col.find(
        {"status": "failed"},
        {"metadata.title": 1, "failed_stage": 1, "error": 1, "retries": 1},
    )
    jobs = await cursor.to_list(length=None)

    if not jobs:
        print("No failed jobs.")
        return

    print(f"\n{len(jobs)} failed job(s)")

    # Group by (failed_stage, error) so the same repeated cause shows up as
    # one line with a count instead of N near-identical rows.
    counts = Counter()
    for job in jobs:
        key = (job.get("failed_stage") or "?", (job.get("error") or "")[:120])
        counts[key] += 1

    print("\n-- By failure reason --")
    for (stage, error), count in counts.most_common():
        print(f"  [{count:>3}] {stage:<14} {error}")

    print(f"\n-- First {min(limit, len(jobs))} individual jobs --")
    for job in jobs[:limit]:
        title = job.get("metadata", {}).get("title", "untitled")
        error = (job.get("error") or "")[:80]
        print(f"  {title[:50]:<50} stage={job.get('failed_stage')} retries={job.get('retries')} error={error}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    asyncio.run(list_failed(limit))
