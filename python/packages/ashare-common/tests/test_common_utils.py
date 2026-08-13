import logging

import pytest
from ashare_common.logging import setup_logging
from ashare_common.observability import init_telemetry, reset_telemetry_for_test


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
    reset_telemetry_for_test()
    first = init_telemetry("svc-a", disabled=True)
    second = init_telemetry("svc-b", disabled=True)
    assert second is first
    first.shutdown()
    reset_telemetry_for_test()
