# Comment task for Chamber Scribe

Add comments to every Python file following these rules:

## Module level
Add a docstring at the top of every file explaining:
- What this file does
- Why it exists (what problem it solves)
- Any important dependencies or quirks

## Classes
Add a docstring explaining:
- What the class represents
- When to use it vs alternatives

## Functions
Add a docstring explaining:
- What it does (one line)
- Args and return value
- Any side effects (DB writes, file deletes, network calls)

## Inline comments
Only comment non-obvious logic. Never comment obvious operations.
Good: explain WHY a business decision was made
Bad: restate what the code already says clearly

## Style rules
- Keep comments concise — one line where possible
- Use present tense: "Returns" not "Return"
- Flag anything that could break with: # NOTE: or # WARNING:
- Flag future work with: # TODO:

## Files to comment (in priority order)
1. services/scraper/portal_registry.py
2. services/downloader/rules.py
3. services/transcriber/transcriber.py
4. services/scraper/scraper.py
5. shared/db/models/job.py
6. services/downloader/downloader.py
7. services/scraper/detectors/senate_portal.py
8. services/scraper/detectors/house_portal.py
9. services/transcriber/engines/vtt_engine.py
10. services/transcriber/engines/whisper.py

## What NOT to comment
- __init__.py files
- Config files with obvious variable names
- Import statements
- Obvious one-liners like col = jobs_collection()