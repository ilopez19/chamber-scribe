"""One-off helper: print excluded jobs grouped by reason. These are jobs the
pipeline deliberately decided not to process (too short, live-channel entry
with no stable recording, etc.) — not errors, so they're worth a periodic
glance but not the thing to triage. For jobs that need a human to check,
see list_failed.py instead.

Usage:
    python -m scripts.list_excluded
    python -m scripts.list_excluded 30      # show more individual rows
"""

import asyncio
import sys
from collections import Counter

from shared.db.database import jobs_collection


async def list_excluded(limit: int) -> None:
    col = jobs_collection()
    cursor = col.find(
        {"status": "excluded"},
        {"metadata.title": 1, "failed_stage": 1, "error": 1},
    )
    jobs = await cursor.to_list(length=None)

    if not jobs:
        print("No excluded jobs.")
        return

    print(f"\n{len(jobs)} excluded job(s)")

    counts = Counter()
    for job in jobs:
        key = (job.get("failed_stage") or "?", (job.get("error") or "")[:120])
        counts[key] += 1

    print("\n-- By exclusion reason --")
    for (stage, error), count in counts.most_common():
        print(f"  [{count:>3}] {stage:<14} {error}")

    print(f"\n-- First {min(limit, len(jobs))} individual jobs --")
    for job in jobs[:limit]:
        title = job.get("metadata", {}).get("title", "untitled")
        error = (job.get("error") or "")[:80]
        print(f"  {title[:50]:<50} stage={job.get('failed_stage')} error={error}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    asyncio.run(list_excluded(limit))
