import logging

import pytest
from ashare_common.logging import setup_logging
from ashare_common.observability import init_telemetry


def test_setup_logging_configures_root_handler() -> None:
    setup_logging("test-service", level="debug")

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1

    handler = root.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.formatter is not None
    formatted = handler.format(
        logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
    )
    # JSON-ish structured output carrying the service name.
    assert '"svc":"test-service"' in formatted
    assert '"msg":"hello"' in formatted


def test_setup_logging_invalid_level_falls_back_to_info() -> None:
    setup_logging("svc", level="not-a-level")
    assert logging.getLogger().level == logging.INFO


def test_init_telemetry_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    monkeypatch.setattr(
        "ashare_common.observability.logger.info",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    init_telemetry("svc-a")
    init_telemetry("svc-b", otlp_endpoint="http://example.com:4318")

    # Second call is a no-op: only one stub activation was logged.
    assert len(calls) == 1
    args = calls[0][0][1:]  # logger uses lazy %-formatting
    assert args[0] == "svc-a"
    assert args[1] == "http://localhost:4318"
