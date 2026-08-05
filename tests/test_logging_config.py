import json
import logging
import sys

from app.logging_config import JsonFormatter


def test_json_formatter_produces_valid_json_with_expected_fields():
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )

    parsed = json.loads(JsonFormatter().format(record))

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test.logger"
    assert parsed["message"] == "hello world"
    assert "timestamp" in parsed


def test_json_formatter_includes_exc_info_when_present():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    parsed = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in parsed["exc_info"]


def test_json_formatter_omits_exc_info_key_when_absent():
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="fine",
        args=(),
        exc_info=None,
    )

    parsed = json.loads(JsonFormatter().format(record))
    assert "exc_info" not in parsed
