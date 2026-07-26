# Central logging setup — every module gets its logger via
# get_logger(__name__) instead of print(), for consistent timestamps/levels
# and one place to change verbosity (LOG_LEVEL env var, default INFO).

import logging
import os
import sys

_configured = False


# Sets up the root logger's handler/format once; safe to call repeatedly.
def configure_logging() -> None:
    global _configured
    if _configured:
        return

    # Windows gives a redirected stdout/stderr the legacy cp1252 encoding
    # instead of UTF-8, which breaks on this codebase's emoji log lines.
    # reconfigure() is best-effort since not every stream type supports it.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        # basicConfig() defaults to stderr, not stdout — without this,
        # every logger.info/warning call would land in .err.log instead
        # of .out.log, the opposite of what those files are for.
        stream=sys.stdout,
    )
    _configured = True


# Returns a module-scoped logger, configuring logging on first use.
# Usage: logger = get_logger(__name__)
def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
