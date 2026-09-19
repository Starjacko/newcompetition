import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOGGER_NAME = "coregeek.agent"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name or LOGGER_NAME)


def configure_logging(log_dir: str | Path | None = None) -> logging.Logger:
    """Configure one process-wide rotating JSONL log without duplicate handlers."""
    logger = get_logger()
    logger.setLevel(os.getenv("AGENT_LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    if logger.handlers:
        return logger

    formatter = JsonFormatter()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    directory = Path(log_dir or os.getenv("AGENT_LOG_DIR", "logs"))
    directory.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        directory / "agent.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def event(
    logger: logging.Logger,
    level: int,
    name: str,
    *,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    logger.log(
        level,
        name,
        extra={"fields": {"event": name, **fields}},
        exc_info=exc_info,
    )
