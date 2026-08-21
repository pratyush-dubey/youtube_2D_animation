"""
Structured logging configuration using structlog.
Call configure_logging() once at app startup.
"""
from __future__ import annotations

import logging
import sys

import structlog

from app.config.settings import settings


def configure_logging() -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Silence SQLAlchemy's own logger unless explicitly in development mode
    if settings.app_env != "development":
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Wrap stdout in a UTF-8 stream so structlog's box-drawing characters
    # don't crash on Windows cp1252 terminals. Errors are replaced with '?'.
    # Fall back to sys.stdout directly if fileno() is unavailable (e.g. Click
    # CliRunner replaces stdout with a StringIO buffer during tests).
    try:
        utf8_stdout = open(
            sys.stdout.fileno(),
            mode="w",
            encoding="utf-8",
            errors="replace",
            closefd=False,
            buffering=1,
        )
    except Exception:
        utf8_stdout = sys.stdout
    handler = logging.StreamHandler(utf8_stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


def get_logger(name: str = "app") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
