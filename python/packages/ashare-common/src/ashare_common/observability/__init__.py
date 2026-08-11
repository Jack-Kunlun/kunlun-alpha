"""OpenTelemetry integration for Python services.

Usage:
    from ashare_common.observability import init_telemetry

    init_telemetry("sample-engine")

The OTLP endpoint defaults to http://localhost:4318 and can be
overridden via OTEL_EXPORTER_OTLP_ENDPOINT env var.
"""

import logging

logger = logging.getLogger(__name__)

_initialized = False


def init_telemetry(
    service_name: str,
    service_version: str = "0.0.0",
    otlp_endpoint: str | None = None,
) -> None:
    """Initialize OpenTelemetry tracing and metrics.

    Currently a no-op stub. To activate:
    1. Install opentelemetry-sdk and opentelemetry-exporter-otlp
    2. Set up your TracerProvider and MeterProvider

    The function signature is designed to be stable so callers
    don't need to change when the underlying implementation changes.
    """
    global _initialized  # noqa: PLW0603
    if _initialized:
        return

    endpoint = otlp_endpoint or "http://localhost:4318"

    # STUB: OTel SDK packages not installed
    logger.info(
        "Telemetry stub activated for %s (endpoint: %s)",
        service_name,
        endpoint,
    )

    _initialized = True
