import { describe, expect, it } from "vitest";
import { notificationInstrumentHref } from "./notification-instrument-link";

describe("notification instrument navigation", () => {
  it("opens the existing current daily route for canonical Shanghai, Shenzhen and Beijing codes", () => {
    for (const code of ["600519.SH", "000001.SZ", "920000.BJ"]) {
      expect(notificationInstrumentHref(code)).toBe(`/instruments/${code}`);
    }
  });

  it("rejects malformed codes and URL-like input instead of producing a link", () => {
    for (const code of [
      "",
      "600519",
      "600519.sh",
      " 600519.SH",
      "00700.HK",
      "../600519.SH",
      "https://example.test",
      "600519.SH?asOf=2026-01-01",
    ]) {
      expect(notificationInstrumentHref(code)).toBeNull();
    }
  });
});
