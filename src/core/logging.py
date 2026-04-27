from __future__ import annotations

import logging
from logging.config import dictConfig


def configure_logging(level: str) -> None:
    if getattr(configure_logging, "_configured", False):
        return

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                }
            },
            "root": {"handlers": ["default"], "level": level.upper()},
        }
    )
    logging.getLogger("websockets").setLevel(logging.INFO)
    configure_logging._configured = True
