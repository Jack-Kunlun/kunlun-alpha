import { describe, expect, it } from "vitest";
import { AppController } from "./app.controller";
import { MetricsController } from "./metrics.controller";
import { apiMetrics } from "./metrics";

describe("Phase 0 API endpoints", () => {
  it("returns a versioned UTC health response", () => {
    const result = new AppController().health();
    expect(result.status).toBe("ok");
    expect(result.version).toBe("0.0.0");
    expect(new Date(result.timestamp).toISOString()).toBe(result.timestamp);
  });

  it("renders Prometheus metrics", () => {
    apiMetrics.recordHttpRequest("GET", "/api/v1/health", 200, 0.01);
    expect(new MetricsController().metrics()).toContain("kunlun_api_http_requests_total");
  });
});
