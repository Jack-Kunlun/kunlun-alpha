import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { capturePaperRiskContext, readPaperRiskPreview } from "./paper-risk-preview";
function fixture(): Record<string, unknown> {
  const raw: unknown = JSON.parse(
    readFileSync(resolve(process.cwd(), "../../data/fixtures/paper-risk-preview-v1.json"), "utf8"),
  );
  if (typeof raw !== "object" || raw === null) throw new Error();
  return raw as Record<string, unknown>;
}
describe("risk report binding and product wording", () => {
  it("binds to the current preview and labels closed execution as a blocker", () => {
    const data = fixture();
    const context = capturePaperRiskContext(data.allocation);
    const risk = readPaperRiskPreview(data.risk, context);
    expect(risk.rows).toHaveLength(10);
    expect(risk.rows.find((r) => r.code === "EXECUTION_CONNECTED")).toMatchObject({
      passed: false,
      actual: "未开放",
    });
    expect(risk.rows.find((r) => r.code === "CASH_AVAILABLE")?.actual).toBe("70000");
  });
  it.each(["allowed", "intent", "basis", "missing", "execution"])(
    "refuses inconsistent %s",
    (field) => {
      const data = fixture(),
        context = capturePaperRiskContext(data.allocation);
      const risk = data.risk as Record<string, unknown>;
      if (field === "allowed") risk.allowed = true;
      if (field === "intent") risk.intentId = "0".repeat(64);
      if (field === "basis") risk.accountStateDigest = "0".repeat(64);
      const checks = risk.checks as Array<Record<string, unknown>>;
      if (field === "missing") checks.pop();
      if (field === "execution") {
        const check = checks.find((c) => c.code === "EXECUTION_CONNECTED")!;
        check.actual = "true";
        check.status = "PASS";
      }
      expect(() => readPaperRiskPreview(risk, context)).toThrow();
    },
  );
  it("refuses an allocation without an intent", () => {
    const data = fixture();
    const a = data.allocation as Record<string, unknown>;
    a.intents = [];
    expect(() => capturePaperRiskContext(a)).toThrow();
  });
});
