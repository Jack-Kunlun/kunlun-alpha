import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  preparePaperReconciliationExport,
  downloadPaperReconciliationExport,
} from "./paper-reconciliation-export";
import { PaperReconciliationExportButton } from "./paper-reconciliation-export-button";
const accountId = "b".repeat(64),
  basis = "2026-10-25T02:00:00Z";
function report() {
  return {
    schemaVersion: "paper-reconciliation-result-v1",
    reconciliationId: "a".repeat(64),
    accountId,
    asOf: "2026-10-25T10:01:00.123456789+08:00",
    status: "MATCHED",
    expectedBookDigest: "c".repeat(64),
    observedBookDigest: "c".repeat(64),
    diffs: [],
    duplicateFillCount: 0,
    executionCapability: "PAPER_ONLY",
    dataMeaning: "SIMULATION_BOOK_RECONCILIATION",
  };
}
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe("paper reconciliation download", () => {
  it("preserves the complete matched contract, nanosecond cutoff and provenance", () => {
    const input = report(),
      before = structuredClone(input);
    const prepared = preparePaperReconciliationExport(input, accountId, basis);
    expect(JSON.parse(prepared.json)).toEqual(before);
    expect(prepared.json.endsWith("\n")).toBe(true);
    expect(prepared.filename).toBe(`paper-reconciliation-20261025T020100Z-${"a".repeat(12)}.json`);
    expect(input).toEqual(before);
  });
  it("preserves exact decimal text and all three difference kinds", () => {
    const input = {
      ...report(),
      status: "DRIFTED",
      observedBookDigest: "d".repeat(64),
      duplicateFillCount: 1,
      diffs: [
        {
          kind: "CASH",
          instrumentId: null,
          expected: "9007199254740993.00000001",
          observed: "9007199254740993",
          difference: "-0.00000001",
        },
        {
          kind: "POSITION_QUANTITY",
          instrumentId: "600519.SH",
          expected: "300",
          observed: "200",
          difference: "-100",
        },
        {
          kind: "POSITION_COST",
          instrumentId: "600519.SH",
          expected: "30009.0010",
          observed: "30009",
          difference: "-0.0010",
        },
      ],
    };
    const { json } = preparePaperReconciliationExport(input, accountId, basis);
    expect(JSON.parse(json)).toEqual(input);
    expect(json).toContain('"expected": "9007199254740993.00000001"');
    expect(json).toContain('"difference": "-0.0010"');
  });
  it.each([
    { accountId: "f".repeat(64) },
    { asOf: "2026-10-25T01:59:59Z" },
    { asOf: "2026-02-30T00:00:00Z" },
    { executionCapability: "LIVE" },
    { status: "DRIFTED" },
    { unknown: true },
  ])("refuses mismatched or invalid data %j", (change) => {
    expect(() =>
      preparePaperReconciliationExport({ ...report(), ...change }, accountId, basis),
    ).toThrow();
  });
  it("keeps downloads unavailable until a valid current check has succeeded", () => {
    const ready = renderToStaticMarkup(
      <PaperReconciliationExportButton report={report()} accountId={accountId} basis={basis} />,
    );
    expect(ready).toContain("下载核对报告");
    expect(ready).toContain("JSON");
    expect(ready).not.toContain('disabled=""');
    for (const props of [
      { report: null },
      { pending: true },
      { disabled: true },
      { checkError: "检查失败" },
      { accountId: "f".repeat(64) },
    ]) {
      const html = renderToStaticMarkup(
        <PaperReconciliationExportButton
          report={report()}
          accountId={accountId}
          basis={basis}
          {...props}
        />,
      );
      expect(html).toContain('disabled=""');
      expect(html).toContain("disabled:cursor-not-allowed");
    }
  });
  it.each([false, true])(
    "cleans temporary browser resources even on a download failure (%s)",
    (failed) => {
      vi.useFakeTimers();
      const remove = vi.fn(),
        append = vi.fn(),
        revokeObjectURL = vi.fn();
      const click = vi.fn(() => {
        if (failed) throw new Error("download blocked");
      });
      const anchor = { href: "", download: "", hidden: false, click, remove };
      vi.stubGlobal("document", { createElement: () => anchor, body: { append } });
      vi.stubGlobal("URL", { createObjectURL: () => "blob:isolated-test", revokeObjectURL });
      const prepared = preparePaperReconciliationExport(report(), accountId, basis);
      if (failed)
        expect(() => downloadPaperReconciliationExport(prepared)).toThrow("download blocked");
      else expect(() => downloadPaperReconciliationExport(prepared)).not.toThrow();
      expect(anchor.download).toBe(prepared.filename);
      expect(anchor.href).toBe("blob:isolated-test");
      expect(append).toHaveBeenCalledWith(anchor);
      expect(remove).toHaveBeenCalledOnce();
      if (!failed) {
        expect(revokeObjectURL).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1000);
      }
      expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:isolated-test");
    },
  );
});
