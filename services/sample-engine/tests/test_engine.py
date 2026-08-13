import pytest
from ashare_common import HealthHandler, ServiceConfig, ServiceRunner


def test_health_handler() -> None:
    health = HealthHandler(service="sample", version="1.0.0")
    result = health.check()
    assert result.status == "ok"
    assert result.service == "sample"
    assert result.version == "1.0.0"


def test_service_config_defaults() -> None:
    config = ServiceConfig()
    assert config.service_name == "kunlun"
    assert config.log_level == "INFO"
    assert config.port == 8080
    assert config.shutdown_timeout_seconds == 10.0


def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KUNLUN_SERVICE_NAME", "test-engine")
    monkeypatch.setenv("KUNLUN_PORT", "9876")
    config = ServiceConfig()
    assert config.service_name == "test-engine"
    assert config.port == 9876


def test_service_runner_has_shutdown_timeout() -> None:
    runner = ServiceRunner(shutdown_timeout=5.0)
    assert runner.shutdown_timeout == 5.0
