import { OTLPMetricExporter } from "@opentelemetry/exporter-metrics-otlp-http";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { PeriodicExportingMetricReader } from "@opentelemetry/sdk-metrics";
import { NodeSDK } from "@opentelemetry/sdk-node";
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from "@opentelemetry/semantic-conventions";

export interface TracingOptions {
  serviceName: string;
  serviceVersion?: string;
  otlpEndpoint?: string;
  disabled?: boolean;
}

export interface TelemetryHandle {
  shutdown(): Promise<void>;
}

let activeHandle: TelemetryHandle | undefined;

export function initTelemetry(options: TracingOptions): TelemetryHandle {
  if (activeHandle) return activeHandle;

  if (options.disabled) {
    activeHandle = { shutdown: async () => undefined };
    return activeHandle;
  }

  const endpoint = (options.otlpEndpoint ?? "http://localhost:4318").replace(/\/$/, "");
  const sdk = new NodeSDK({
    resource: resourceFromAttributes({
      [ATTR_SERVICE_NAME]: options.serviceName,
      [ATTR_SERVICE_VERSION]: options.serviceVersion ?? "0.0.0",
    }),
    traceExporter: new OTLPTraceExporter({ url: `${endpoint}/v1/traces` }),
    metricReader: new PeriodicExportingMetricReader({
      exporter: new OTLPMetricExporter({ url: `${endpoint}/v1/metrics` }),
    }),
  });
  sdk.start();

  activeHandle = {
    async shutdown() {
      await sdk.shutdown();
      activeHandle = undefined;
    },
  };
  return activeHandle;
}
