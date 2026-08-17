import { describe, expect, it } from "vitest";
import {
  QualityValidationError,
  validateEvidenceId,
  validateQualityQuery,
} from "./quality-filters";

describe("validateQualityQuery", () => {
  it("accepts suffix-form unifiedCode and date", () => {
    expect(validateQualityQuery({ date: "2026-08-13", unifiedCode: "600519.SH" })).toEqual({
      date: "2026-08-13",
      unifiedCode: "600519.SH",
    });
  });

  it("rejects the legacy prefix form SH.600519", () => {
    expect(() => validateQualityQuery({ unifiedCode: "SH.600519" })).toThrow(QualityValidationError);
  });

  it("rejects path traversal in source", () => {
    expect(() => validateQualityQuery({ source: "../etc/passwd" })).toThrow(QualityValidationError);
    expect(() => validateQualityQuery({ source: "a/b" })).toThrow(QualityValidationError);
  });

  it("rejects illegal dates", () => {
    expect(() => validateQualityQuery({ date: "2026-13-45" })).toThrow(QualityValidationError);
    expect(() => validateQualityQuery({ date: "not-a-date" })).toThrow(QualityValidationError);
  });

  it("rejects unknown filter keys", () => {
    expect(() => validateQualityQuery({ evil: "x" })).toThrow(QualityValidationError);
  });

  it("rejects a date range where from > to", () => {
    expect(() =>
      validateQualityQuery({ dateFrom: "2026-08-14", dateTo: "2026-08-13" }),
    ).toThrow(QualityValidationError);
  });

  it("rejects non-object input", () => {
    expect(() => validateQualityQuery("date=2026-08-13")).toThrow(QualityValidationError);
  });
});

describe("validateEvidenceId", () => {
  it("accepts a safe internal id", () => {
    expect(validateEvidenceId("fund-conflict-abc123")).toBe("fund-conflict-abc123");
  });

  it("rejects path traversal and unsafe characters", () => {
    expect(() => validateEvidenceId("../../etc/passwd")).toThrow(QualityValidationError);
    expect(() => validateEvidenceId("raw/objects/abc")).toThrow(QualityValidationError);
    expect(() => validateEvidenceId("Bearer token")).toThrow(QualityValidationError);
  });
});
