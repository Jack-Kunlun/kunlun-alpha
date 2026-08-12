import { describe, expect, it } from "vitest";
import { createLogger, generateId } from "./logger.js";

describe("createLogger", () => {
  it("emits a JSON line carrying the service name and level", () => {
    const logs: string[] = [];
    const original = console.log;
    console.log = (line: string) => logs.push(line);
    try {
      const logger = createLogger({ service: "test-service" });
      logger.info("hello");
    } finally {
      console.log = original;
    }

    expect(logs).toHaveLength(1);
    const entry = JSON.parse(logs[0] as string) as Record<string, unknown>;
    expect(entry.service).toBe("test-service");
    expect(entry.level).toBe("info");
    expect(entry.message).toBe("hello");
    expect(entry.timestamp).toBeTruthy();
  });

  it("merges per-call metadata into the entry", () => {
    const logs: string[] = [];
    const original = console.log;
    console.log = (line: string) => logs.push(line);
    try {
      createLogger({ service: "svc" }).warn("slow", { latencyMs: 12 });
    } finally {
      console.log = original;
    }

    const entry = JSON.parse(logs[0] as string) as Record<string, unknown>;
    expect(entry.level).toBe("warn");
    expect(entry.latencyMs).toBe(12);
  });

  it("child() inherits and extends the parent context", () => {
    const logs: string[] = [];
    const originalLog = console.log;
    const originalError = console.error;
    console.log = (line: string) => logs.push(line);
    console.error = (line: string) => logs.push(line);
    try {
      const logger = createLogger({ service: "api" });
      logger.child({ requestId: "req-1" }).error("boom");
    } finally {
      console.log = originalLog;
      console.error = originalError;
    }

    const entry = JSON.parse(logs[0] as string) as Record<string, unknown>;
    expect(entry.service).toBe("api");
    expect(entry.requestId).toBe("req-1");
    expect(entry.level).toBe("error");
  });
});

describe("generateId", () => {
  it("returns a UUID v4 string", () => {
    expect(generateId()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });

  it("returns distinct values across calls", () => {
    expect(generateId()).not.toBe(generateId());
  });
});
