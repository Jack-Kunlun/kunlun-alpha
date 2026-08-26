import { describe, expect, it } from "vitest";
import { isRfc3339Instant } from "./rfc3339";

describe("isRfc3339Instant", () => {
  it.each(["2026-08-24T03:00:00Z", "2026-08-24T11:00:00.123+08:00", "2026-08-24T01:00:00-02:00"])(
    "accepts a real instant with an explicit offset: %s",
    (value) => {
      expect(isRfc3339Instant(value)).toBe(true);
    },
  );

  it.each([
    "2026-02-30T00:00:00Z",
    "2026-08-24T15:00:00",
    "2026-08-24T24:00:00Z",
    "2026-08-24T03:00:00-00:00",
  ])("rejects a non-instant or invalid calendar value: %s", (value) => {
    expect(isRfc3339Instant(value)).toBe(false);
  });
});
