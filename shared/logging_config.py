"""Central logging setup.

Every pipeline module gets its logger via get_logger(__name__) instead of
calling print() directly. That gives consistent timestamps/levels across
the whole system, a single place to change the format or redirect output
(e.g. to a file or a log aggregator) later, and the ability to turn
verbosity up or down without touching call sites.

Scope note: the one-off scripts under scripts/ (db_utils.py, list_failed.py,
etc.) intentionally still use print() — their whole purpose is formatted
output for a human reading the terminal directly, not operational logging
for a service running unattended. Timestamps/logger-name prefixes would
just clutter that output. Same for the deliberate progress-bar line in
downloader/strategies/http.py, which overwrites itself in place — logging
has no equivalent to print(..., end="\\r").

LOG_LEVEL is read from the environment (default INFO), so verbosity can
be raised without a code change: LOG_LEVEL=DEBUG python main.py
"""

import logging
import os

_configured = False


def configure_logging() -> None:
    """Set up the root logger's handler/format once. Safe to call more
    than once — every call after the first is a no-op.
    """
    global _configured
    if _configured:
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger (configuring logging on first use).

    Usage, at the top of any module:
        from shared.logging_config import get_logger
        logger = get_logger(__name__)
    """
    configure_logging()
    return logging.getLogger(name)
