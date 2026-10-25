import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { readPaperReconciliation } from "./paper-reconciliation";
import { PaperReconciliationResult } from "./paper-reconciliation-card";
const accountId = "b".repeat(64),
  basis = "2026-10-25T02:00:00Z";
function report() {
  return {
    schemaVersion: "paper-reconciliation-result-v1",
    reconciliationId: "a".repeat(64),
    accountId,
    asOf: "2026-10-25T02:01:00Z",
    status: "MATCHED",
    expectedBookDigest: "c".repeat(64),
    observedBookDigest: "c".repeat(64),
    diffs: [],
    duplicateFillCount: 0,
    executionCapability: "PAPER_ONLY",
    dataMeaning: "SIMULATION_BOOK_RECONCILIATION",
  };
}
describe("paper reconciliation report", () => {
  it("binds the report to the current account and workspace time", () => {
    expect(readPaperReconciliation(report(), accountId, basis).status).toBe("MATCHED");
    for (const change of [
      { accountId: "f".repeat(64) },
      { asOf: "2026-10-25T01:59:59Z" },
      { status: "DRIFTED" },
      { executionCapability: "LIVE" },
      { duplicateFillCount: -1 },
    ])
      expect(() => readPaperReconciliation({ ...report(), ...change }, accountId, basis)).toThrow();
  });
  it("shows a timestamped match, busy native action, and failure with the previous report", () => {
    const result = readPaperReconciliation(report(), accountId, basis);
    const html = renderToStaticMarkup(
      <PaperReconciliationResult report={result} pending={false} error={null} onCheck={() => {}} />,
    );
    expect(html).toContain("账簿一致");
    expect(html).toContain("核对时间");
    expect(html).toContain("现金、持仓数量和持仓成本");
    const busy = renderToStaticMarkup(
      <PaperReconciliationResult report={result} pending error={null} onCheck={() => {}} />,
    );
    expect(busy).toContain('disabled=""');
    expect(busy).toContain('aria-busy="true"');
    expect(busy).toContain("disabled:cursor-progress");
    const failed = renderToStaticMarkup(
      <PaperReconciliationResult
        report={result}
        pending={false}
        error="核对暂不可用"
        onCheck={() => {}}
      />,
    );
    expect(failed).toContain("上次成功返回的报告");
    expect(failed).toContain("重试核对");
    expect(failed).toContain('role="alert"');
    expect(failed).toContain("账簿一致");
  });
  it("shows exact signed differences and repeat-fill count without claiming correction", () => {
    const result = readPaperReconciliation(
      {
        ...report(),
        status: "DRIFTED",
        observedBookDigest: "d".repeat(64),
        duplicateFillCount: 1,
        diffs: [
          {
            kind: "POSITION_COST",
            instrumentId: "600519.SH",
            expected: "30009.00000001",
            observed: "30009",
            difference: "-0.00000001",
          },
        ],
      },
      accountId,
      basis,
    );
    const html = renderToStaticMarkup(
      <PaperReconciliationResult report={result} pending={false} error={null} onCheck={() => {}} />,
    );
    expect(html).toContain("发现账簿差异");
    expect(html).toContain("持仓成本");
    expect(html).toContain("-0.00000001");
    expect(html).toContain("去重成交：1");
    expect(html).toContain("不会修复或修改账本");
    expect(html).not.toContain("POSITION_COST");
  });
  it("shows an explicit empty state and unavailable busy action", () => {
    const html = renderToStaticMarkup(
      <PaperReconciliationResult
        report={null}
        pending={false}
        error={null}
        disabled
        onCheck={() => {}}
      />,
    );
    expect(html).toContain("尚未核对");
    expect(html).toContain('disabled=""');
  });
});
