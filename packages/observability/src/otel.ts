/**
 * OpenTelemetry integration layers.
 *
 * These integrations are optional — the observability package works
 * without them. Install @opentelemetry/* packages and import these
 * modules at service startup to enable tracing/metrics.
 *
 * Node.js (apps/api):
 *   import "@kunlun/observability/otel-node";
 *
 * Python (services/):
 *   from ashare_common.observability import init_telemetry
 *   init_telemetry("my-service")
 *
 * The OTLP endpoint defaults to http://localhost:4318 and can be
 * overridden via OTEL_EXPORTER_OTLP_ENDPOINT env var.
 */
