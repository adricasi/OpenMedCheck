"""Logging: allowlisted JSON fields only, no context values (NFR-002, NFR-007)."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest

from openmedcheck import logging_setup
from tests.model_helpers import make_request


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    buffer = io.StringIO()
    logging_setup.configure_logging(buffer)
    yield buffer
    logger = logging.getLogger(logging_setup.LOGGER_NAME)
    logger.handlers.clear()
    logger.propagate = True


def _lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_nfr_007_one_json_line_with_the_check_fields(stream: io.StringIO) -> None:
    logger = logging.getLogger("openmedcheck.check")
    logging_setup.log_event(
        logger,
        logging_setup.CHECK_EVENT,
        request_id="abc123",
        preset_id="A",
        rule_ids=["R-1", "R-2"],
        rules_status="NO_ISSUE",
        final_status="BLOCKED",
        rules_latency_ms=3,
        model_latency_ms=1500,
        model_outcome="ok",
        downgrade_rejected=False,
    )
    (line,) = _lines(stream)
    assert line["event"] == "check"
    assert line["level"] == "INFO"
    assert line["request_id"] == "abc123"
    assert line["rule_ids"] == ["R-1", "R-2"]
    assert line["model_outcome"] == "ok"
    assert line["downgrade_rejected"] is False
    assert "ts" in line


def test_nfr_002_unknown_and_non_scalar_fields_are_dropped(stream: io.StringIO) -> None:
    request = make_request(ed_note="SECRET-NOTE-TEXT-9917")
    logger = logging.getLogger("openmedcheck.check")
    logging_setup.log_event(
        logger,
        "check",
        request_id="abc",
        ed_note=request.context.ed_note,
        context=request.context,
        raw_model_output="SECRET-RAW-OUTPUT",
        rule_ids=[request.context],  # type: ignore[list-item]
        model_outcome={"nested": "SECRET-DICT"},
    )
    text = stream.getvalue()
    assert "SECRET" not in text
    (line,) = _lines(stream)
    assert set(line) == {"ts", "level", "logger", "event", "request_id"}


def test_nfr_002_formatter_ignores_message_args_extras_and_tracebacks(
    stream: io.StringIO,
) -> None:
    logger = logging.getLogger("openmedcheck.web")
    try:
        raise ValueError("SECRET-IN-EXCEPTION")
    except ValueError:
        logger.exception(
            "failed for SECRET-IN-MESSAGE %s", "SECRET-ARG", extra={"body": "SECRET-X"}
        )
    text = stream.getvalue()
    assert "SECRET" not in text
    (line,) = _lines(stream)
    assert line["event"] == "unspecified"
    assert line["level"] == "ERROR"


def test_values_are_truncated(stream: io.StringIO) -> None:
    logging_setup.log_event(
        logging.getLogger("openmedcheck.check"),
        "x" * 500,
        request_id="r" * 500,
        rule_ids=["q" * 500] * 100,
    )
    (line,) = _lines(stream)
    assert len(str(line["event"])) == logging_setup.MAX_TEXT_LENGTH
    assert len(str(line["request_id"])) == logging_setup.MAX_TEXT_LENGTH
    rule_ids = line["rule_ids"]
    assert isinstance(rule_ids, list)
    assert len(rule_ids) == logging_setup.MAX_LIST_ITEMS


def test_configure_logging_is_idempotent_and_does_not_propagate() -> None:
    first, second = io.StringIO(), io.StringIO()
    logging_setup.configure_logging(first)
    logger = logging_setup.configure_logging(second)
    try:
        assert len(logger.handlers) == 1
        assert logger.propagate is False
        logger.info("hello", extra={"event": "ping"})
        assert first.getvalue() == ""
        assert json.loads(second.getvalue())["event"] == "ping"
    finally:
        logger.handlers.clear()
        logger.propagate = True


def test_configure_logging_defaults_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    logger = logging_setup.configure_logging()
    try:
        logging_setup.log_event(logger, "ping", request_id="r1")
        assert json.loads(capsys.readouterr().out)["request_id"] == "r1"
    finally:
        logger.handlers.clear()
        logger.propagate = True


def test_filter_fields_only_returns_allowlisted_keys() -> None:
    kept = logging_setup.filter_fields({"request_id": "a", "note": "b", "http_status": 200})
    assert kept == {"request_id": "a", "http_status": 200}
