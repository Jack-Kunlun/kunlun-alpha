import { describe, expect, it } from "vitest";
import { evidenceUrl } from "./use-data-quality";

describe("evidenceUrl", () => {
  it("points only to the safe internal endpoint", () => {
    expect(evidenceUrl("fund-conflict-aaa")).toBe("/v1/data-quality/fund-conflict-aaa/evidence");
  });

  it("never leaks a raw object path or credential", () => {
    const url = evidenceUrl("fund-conflict-aaa");
    expect(url).not.toContain("raw://");
    expect(url).not.toContain("s3://");
    expect(url).not.toContain("token");
    expect(url).not.toContain("dsn");
  });
});
