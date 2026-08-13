import threading
from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@dataclass
class TelemetryHandle:
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None

    def shutdown(self) -> None:
        if self.tracer_provider is not None:
            self.tracer_provider.shutdown()
        if self.meter_provider is not None:
            self.meter_provider.shutdown()


_lock = threading.Lock()
_handle: TelemetryHandle | None = None


def init_telemetry(
    service_name: str,
    service_version: str = "0.0.0",
    otlp_endpoint: str | None = None,
    *,
    disabled: bool = False,
) -> TelemetryHandle:
    global _handle
    with _lock:
        if _handle is not None:
            return _handle
        if disabled:
            _handle = TelemetryHandle()
            return _handle

        endpoint = (otlp_endpoint or "http://localhost:4318").rstrip("/")
        resource = Resource.create({SERVICE_NAME: service_name, SERVICE_VERSION: service_version})
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"))
            ],
        )
        trace.set_tracer_provider(tracer_provider)
        metrics.set_meter_provider(meter_provider)
        _handle = TelemetryHandle(tracer_provider, meter_provider)
        return _handle


def reset_telemetry_for_test() -> None:
    global _handle
    _handle = None
