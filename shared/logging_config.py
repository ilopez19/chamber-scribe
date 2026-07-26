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
import sys

_configured = False


def configure_logging() -> None:
    """Set up the root logger's handler/format once. Safe to call more
    than once — every call after the first is a no-op.
    """
    global _configured
    if _configured:
        return

    # Windows gives a redirected (non-console) stdout/stderr the legacy
    # code page (e.g. cp1252) instead of UTF-8, and this codebase logs
    # emoji (checkmark/cross marks) in ordinary success/failure lines
    # throughout the download strategies and elsewhere. Without this, every
    # such line fails to encode, gets silently dropped by the logging
    # module, and a "--- Logging error ---" traceback gets dumped to
    # stderr instead of the actual message — which is what showed up in
    # logs\pipeline.err.log in place of a plain "Connected to MongoDB"
    # line. reconfigure() is best-effort since not every stream type
    # supports it (e.g. some test/CI redirections).
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
        # logging.basicConfig() defaults to a StreamHandler on stderr, not
        # stdout — which meant every logger.info/warning/error call in the
        # whole pipeline was silently landing in logs\pipeline.err.log
        # while logs\pipeline.out.log (what start.ps1/start.sh redirect
        # stdout to, and what the README and normal log-checking advice
        # point at) stayed empty. Pointed at stdout explicitly so the
        # out/err file split actually matches its intent: .out.log for
        # normal operation, .err.log reserved for a genuine crash the
        # interpreter itself prints outside of logging entirely.
        stream=sys.stdout,
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
