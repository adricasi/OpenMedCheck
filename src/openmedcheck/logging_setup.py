"""One-line JSON logs with allowlisted fields only (NFR-002, NFR-007).

Patient data, request bodies, 422 bodies and raw model output must never reach a log.
The formatter therefore never emits free-text messages or tracebacks: it writes the level,
logger name, an ``event`` label and the allowlisted ``fields`` it is handed, nothing else.
"""

from __future__ import annotations

import json
import logging
import math
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, TextIO

LOGGER_NAME = "openmedcheck"
CHECK_EVENT = "check"
MAX_TEXT_LENGTH = 64
MAX_LIST_ITEMS = 50

ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "request_id",
        "preset_id",
        "rule_ids",
        "rules_status",
        "rules_risk_level",
        "model_status",
        "model_risk_level",
        "final_status",
        "final_risk_level",
        "source",
        "rules_latency_ms",
        "model_latency_ms",
        "total_latency_ms",
        "model_outcome",
        "model_attempts",
        "invalid_reason",
        "downgrade_rejected",
        "prompt_version",
        "http_method",
        "http_path",
        "http_status",
    }
)


def filter_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Keep allowlisted keys with scalar (or short list of string) values only."""
    return {
        key: _clean_value(value)
        for key, value in fields.items()
        if key in ALLOWED_FIELDS and _is_loggable(value)
    }


def _is_loggable(value: object) -> bool:
    if isinstance(value, list | tuple):
        return all(isinstance(item, str) for item in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, bool | int | str)


def _clean_value(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [item[:MAX_TEXT_LENGTH] for item in value[:MAX_LIST_ITEMS]]
    if isinstance(value, str):
        return value[:MAX_TEXT_LENGTH]
    return value


class JsonFormatter(logging.Formatter):
    """Format a record as one JSON object; only ``record.fields`` is read for data."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": _event_label(record),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, Mapping):
            entry.update(filter_fields(fields))
        return json.dumps(entry, separators=(",", ":"), allow_nan=False)


def _event_label(record: logging.LogRecord) -> str:
    event = getattr(record, "event", None)
    return event[:MAX_TEXT_LENGTH] if isinstance(event, str) else "unspecified"


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit one structured line; unknown or non-scalar fields are dropped."""
    logger.log(level, event, extra={"event": event, "fields": filter_fields(fields)})


def configure_logging(stream: TextIO | None = None, level: int = logging.INFO) -> logging.Logger:
    """Attach the JSON handler to the ``openmedcheck`` logger (idempotent, no propagation)."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        if isinstance(handler.formatter, JsonFormatter):
            logger.removeHandler(handler)
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
