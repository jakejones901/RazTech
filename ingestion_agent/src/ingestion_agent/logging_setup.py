"""Structured logging helpers for the Ingestion Agent."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a log record to JSON.

        Args:
            record: The log record to format.

        Returns:
            A JSON string containing standard and extra fields.
        """
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Attach structured extras commonly used by the pipeline.
        for key in (
            "video_id",
            "path",
            "event",
            "duration_ms",
            "reason",
            "output_directory",
            "component",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, default=str)


class ProcessingLogHandler(logging.Handler):
    """Collect structured log lines for a single recording's processing.log."""

    def __init__(self) -> None:
        """Initialize an in-memory handler."""
        super().__init__(level=logging.DEBUG)
        self.records: list[dict[str, Any]] = []
        self.setFormatter(JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        """Store a formatted JSON log line.

        Args:
            record: The log record to capture.
        """
        try:
            line = self.format(record)
            self.records.append(json.loads(line))
        except Exception:  # noqa: BLE001 — never break logging
            self.handleError(record)

    def write_to(self, path: Path) -> None:
        """Write collected records as newline-delimited JSON.

        Args:
            path: Destination file path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for item in self.records:
                fh.write(json.dumps(item, default=str) + "\n")


def setup_logging(
    level: str = "INFO",
    fmt: str = "json",
    console: bool = True,
    log_file: Optional[str | Path] = None,
    logger_name: str = "ingestion_agent",
) -> logging.Logger:
    """Configure and return the package logger.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR).
        fmt: ``\"json\"`` for structured logs or ``\"text\"`` for human-readable.
        console: Whether to emit logs to stderr.
        log_file: Optional path for a persistent log file.
        logger_name: Logger hierarchy name.

    Returns:
        The configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    formatter: logging.Formatter
    if fmt == "json":
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )

    if console:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "ingestion_agent") -> logging.Logger:
    """Return a child or package logger.

    Args:
        name: Logger name.

    Returns:
        A :class:`logging.Logger` instance.
    """
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    message: str,
    level: int = logging.INFO,
    **extra: Any,
) -> None:
    """Log a structured event with arbitrary extra fields.

    Args:
        logger: Target logger.
        message: Human-readable message.
        level: Logging level constant.
        **extra: Structured fields attached to the record.
    """
    logger.log(level, message, extra=extra)
