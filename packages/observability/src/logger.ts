import { randomUUID } from "node:crypto";

/**
 * Structured JSON logger that carries request context (requestId, traceId).
 *
 * Outputs JSON lines to stdout for easy ingestion by log aggregators.
 * Designed to be replaced with OpenTelemetry/Winston later without API changes.
 */
export interface StructuredLogger {
  info(message: string, meta?: Record<string, unknown>): void;
  warn(message: string, meta?: Record<string, unknown>): void;
  error(message: string, meta?: Record<string, unknown>): void;
  child(defaults: Record<string, unknown>): StructuredLogger;
}

class ConsoleLogger implements StructuredLogger {
  private defaults: Record<string, unknown>;

  constructor(service: string, extra?: Record<string, unknown>) {
    this.defaults = { service, ...extra };
  }

  info(message: string, meta?: Record<string, unknown>): void {
    this.log("info", message, meta);
  }

  warn(message: string, meta?: Record<string, unknown>): void {
    this.log("warn", message, meta);
  }

  error(message: string, meta?: Record<string, unknown>): void {
    this.log("error", message, meta);
  }

  child(defaults: Record<string, unknown>): StructuredLogger {
    return new ConsoleLogger("", { ...this.defaults, ...defaults });
  }

  private log(level: string, message: string, meta?: Record<string, unknown>): void {
    const entry: Record<string, unknown> = {
      ...this.defaults,
      level,
      message,
      timestamp: new Date().toISOString(),
      ...meta,
    };
    console[level === "error" ? "error" : "log"](JSON.stringify(entry));
  }
}

export interface LoggerOptions {
  /** Service name added to every log entry */
  service: string;
  /** Minimum log level (default: info). Set via LOG_LEVEL env var on init. */
  level?: string;
}

/**
 * Create a structured JSON logger.
 *
 * Call this once per service at startup.
 * For per-request logging, use logger.child({ requestId, traceId }).
 */
export function createLogger(options: LoggerOptions): StructuredLogger {
  return new ConsoleLogger(options.service);
}

/** Generate a UUID v4 for request/trace IDs */
export function generateId(): string {
  return randomUUID();
}
