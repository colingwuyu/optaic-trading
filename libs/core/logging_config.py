from __future__ import annotations

import logging

import structlog

from libs.core.settings import Settings

def _resolve_level(level_name: str) -> int:
    level = logging.getLevelName(level_name.upper())
    if isinstance(level, str):
        return logging.INFO
    return level

def configure_logging(settings: Settings) -> None:
    level = _resolve_level(settings.log_level)
    logging.basicConfig(level=level, format="%(message)s")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
