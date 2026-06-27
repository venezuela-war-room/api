"""Logging setup for the `app` namespace.

Attaches a stream handler to the top-level ``app`` logger so messages from
``app.geocoding_worker`` (and friends) are actually emitted — by default Python's root
logger only shows WARNING+, which would hide the worker's INFO progress lines. Scoped to
``app`` so it doesn't disturb uvicorn's own loggers.
"""

import logging

from app.config import settings

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configure_logging() -> None:
    level = settings.log_level.upper()
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    if not any(getattr(h, "_tvwr", False) for h in app_logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._tvwr = True  # marker so we don't add a second handler on re-call
        app_logger.addHandler(handler)
    # Handle records here; don't also bubble up to the root logger (avoids duplicates).
    app_logger.propagate = False
