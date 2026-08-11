/**
 * Placeholder for OpenTelemetry SDK initialization.
 *
 * When OTel SDK packages are installed, replace this with:
 *
 *   import { NodeSDK } from "@opentelemetry/sdk-node";
 *   import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
 *   ...
 *
 * The API surface (initTelemetry options) is designed to be
 * stable so that callers don't need to change when we swap
 * the underlying implementation.
 */

/** Options passed to initTelemetry */
export interface TracingOptions {
  /** Service name for resource attributes */
  serviceName: string;
  /** Service version (default: 0.0.0) */
  serviceVersion?: string;
  /** OTLP HTTP endpoint (default: http://localhost:4318) */
  otlpEndpoint?: string;
}

/**
 * Initialize OpenTelemetry tracing and metrics.
 *
 * Currently a no-op stub. To activate:
 * 1. Install @opentelemetry/sdk-node, @opentelemetry/exporter-trace-otlp-http,
 *    @opentelemetry/exporter-metrics-otlp-http, @opentelemetry/sdk-metrics
 * 2. Replace this implementation with the actual NodeSDK setup
 */
export function initTelemetry(_options: TracingOptions): void {
  // Stub — OTel SDK packages not installed
}
