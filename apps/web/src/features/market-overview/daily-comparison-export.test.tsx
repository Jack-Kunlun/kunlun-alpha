import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { version as applicationVersion } from "../../../package.json";
import {
  buildDailyComparison,
  type DailyComparison,
  type DailyComparisonOutcome,
  type DailyComparisonSort,
} from "./daily-comparison";
import { DailyComparisonExportButton } from "./daily-comparison-export-button";
import { prepareDailyComparisonSnapshot } from "./daily-comparison-export";

const AS_OF = "2026-10-26T02:00:00.123456789Z";
const SORT: DailyComparisonSort = { key: "amount", direction: "ascending" };
function comparison(): DailyComparison {
  const stocks = [
    { instrumentId: "000001.SZ", name: "示例一", sector: "" },
    { instrumentId: "600519.SH", name: "示例二", sector: "" },
  ];
  const outcomes: DailyComparisonOutcome[] = stocks.map((stock, index) => ({
    stock,
    kind: "response",
    value: {
      schemaVersion: "instrument-bars-v1",
      dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
      instrumentId: stock.instrumentId,
      mode: "HISTORICAL",
      requestedAsOf: AS_OF,
      effectiveAsOf: AS_OF,
      interval: "DAILY",
      priceType: "RAW",
      status: "AVAILABLE",
      barCount: 2,
      bars: ["2026-10-22", "2026-10-23"].map((date, i) => ({
        date,
        eventTime: `${date}T07:00:00Z`,
        availableTime: `${date}T07:01:00Z`,
        processingTime: `${date}T07:02:00Z`,
        close:
          index === 0
            ? i === 0
              ? "9007199254740993.00000000"
              : "9007199254740993.00000001"
            : i === 0
              ? "10.0000"
              : "11.0000",
        amount: index === 0 ? "9007199254740993.00000002" : "9007199254740993.00000001",
        suspended: false,
        source: "test-provider",
        sourceVersion: "provider-v1",
        dataVersion: "data-v1",
      })),
    },
  }));
  return buildDailyComparison(AS_OF, outcomes, stocks);
}

describe("daily comparison local snapshot", () => {
  it("retains valid calculation restrictions instead of inventing a change", () => {
    const data = comparison();
    const stocks = data.rows.map((row) => ({
      instrumentId: row.instrumentId,
      name: row.name,
      sector: "",
    }));
    const outcomes: DailyComparisonOutcome[] = data.rows.map((row, index) => ({
      stock: stocks[index]!,
      kind: "response",
      value: {
        schemaVersion: "instrument-bars-v1",
        dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
        instrumentId: row.instrumentId,
        mode: "HISTORICAL",
        requestedAsOf: AS_OF,
        effectiveAsOf: AS_OF,
        interval: "DAILY",
        priceType: "RAW",
        status: "AVAILABLE",
        barCount: 2,
        bars: [
          { ...row.previous!, sourceVersion: index === 1 ? "older-v1" : "provider-v1" },
          { ...row.latest!, suspended: index === 0 },
        ],
      },
    }));
    const doc = JSON.parse(
      prepareDailyComparisonSnapshot(buildDailyComparison(AS_OF, outcomes, stocks), AS_OF, SORT)
        .json,
    );
    expect(doc.rows.every((row: { changePercent: unknown }) => row.changePercent === null)).toBe(
      true,
    );
    expect(doc.rows.map((row: { changeReason: string }) => row.changeReason)).toEqual(
      expect.arrayContaining(["来源版本不一致", "停牌，不计算涨跌幅"]),
    );
  });
  it("preserves the captured cutoff, exact text, provenance and current decimal sort without mutation", () => {
    const data = comparison(),
      before = structuredClone(data);
    const prepared = prepareDailyComparisonSnapshot(data, AS_OF, SORT);
    const doc = JSON.parse(prepared.json);
    expect(doc.schemaVersion).toBe("daily-comparison-snapshot-v1");
    expect(doc.calculationVersion).toBe("visible-close-change-v1");
    expect(doc.applicationVersion).toBe(applicationVersion);
    expect(doc.scope).toBe("WATCHLIST_VISIBLE_PAGE");
    expect(doc.requestedAsOf).toBe(AS_OF);
    expect(doc.sort).toEqual(SORT);
    expect(doc.sampleCount).toBe(2);
    expect(doc.rows.map((row: { instrumentId: string }) => row.instrumentId)).toEqual([
      "600519.SH",
      "000001.SZ",
    ]);
    expect(doc.rows[1].latest.close).toBe("9007199254740993.00000001");
    expect(doc.rows[1].previous.close).toBe("9007199254740993.00000000");
    expect(doc.rows[0].changeHundredthsOfPercent).toBe("1000");
    expect(doc.rows[0].changePercent).toBe("+10.00%");
    expect(doc.rows[1].latest.sourceVersion).toBe("provider-v1");
    expect(doc.comparisonDate).toBe("2026-10-23");
    expect(doc.baselineDate).toBe("2026-10-22");
    expect(prepared.filename).toBe("daily-comparison-20261026T020000123Z-2.json");
    expect(prepared.json.endsWith("\n")).toBe(true);
    expect(data).toEqual(before);
  });
  it("exports reverse order and excludes unknown fields from both the document and rows", () => {
    const data = comparison();
    Object.assign(data, { privateCanary: "not-exported" });
    Object.assign(data.rows[0]!, { privateCanary: "not-exported" });
    Object.assign(data.rows[0]!.latest!, { privateCanary: "not-exported" });
    const result = prepareDailyComparisonSnapshot(data, AS_OF, {
      ...SORT,
      direction: "descending",
    });
    expect(result.json).not.toContain("privateCanary");
    expect(
      JSON.parse(result.json).rows.map((row: { instrumentId: string }) => row.instrumentId),
    ).toEqual(["000001.SZ", "600519.SH"]);
  });
  it("preserves missing, error, forbidden and invalid rows as explicit nulls", () => {
    const stocks = ["600000.SH", "600001.SH", "600002.SH", "600003.SH"].map((instrumentId) => ({
      instrumentId,
      name: "示例",
      sector: "",
    }));
    const outcomes: DailyComparisonOutcome[] = [
      { stock: stocks[0]!, kind: "error" },
      { stock: stocks[1]!, kind: "forbidden" },
      { stock: stocks[2]!, kind: "response", value: {} },
      {
        stock: stocks[3]!,
        kind: "response",
        value: {
          schemaVersion: "instrument-bars-v1",
          dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
          instrumentId: stocks[3]!.instrumentId,
          mode: "HISTORICAL",
          requestedAsOf: AS_OF,
          effectiveAsOf: AS_OF,
          interval: "DAILY",
          priceType: "RAW",
          status: "EMPTY",
          barCount: 0,
          bars: [],
        },
      },
    ];
    const doc = JSON.parse(
      prepareDailyComparisonSnapshot(buildDailyComparison(AS_OF, outcomes, stocks), AS_OF, SORT)
        .json,
    );
    expect(doc.rows.map((row: { status: string }) => row.status)).toEqual([
      "ERROR",
      "FORBIDDEN",
      "INVALID",
      "EMPTY",
    ]);
    expect(
      doc.rows.every(
        (row: { latest: unknown; previous: unknown; changePercent: unknown }) =>
          row.latest === null && row.previous === null && row.changePercent === null,
      ),
    ).toBe(true);
    expect(doc.comparisonDate).toBeNull();
  });
  it("refuses a different query or forged derived result", () => {
    expect(() =>
      prepareDailyComparisonSnapshot(comparison(), "2026-10-26T03:00:00Z", SORT),
    ).toThrow();
    for (const mutate of [
      (data: DailyComparison) => {
        data.baselineDate = "2026-10-21";
      },
      (data: DailyComparison) => {
        data.rows[0]!.changeHundredthsOfPercent = 99n;
      },
      (data: DailyComparison) => {
        data.rows[0]!.dateAligned = false;
      },
      (data: DailyComparison) => {
        data.rows[0]!.latest!.availableTime = "2026-10-26T02:00:00.123456790Z";
      },
      (data: DailyComparison) => {
        data.rows[0]!.instrumentId = "HK:00700";
      },
    ]) {
      const data = comparison();
      mutate(data);
      expect(() => prepareDailyComparisonSnapshot(data, AS_OF, SORT)).toThrow();
    }
  });
  it("rejects empty, duplicate, oversized selections and unsupported sort options", () => {
    const data = comparison();
    for (const rows of [
      [],
      [data.rows[0]!, data.rows[0]!],
      Array.from({ length: 21 }, () => data.rows[0]!),
    ])
      expect(() => prepareDailyComparisonSnapshot({ ...data, rows }, AS_OF, SORT)).toThrow();
    expect(() =>
      prepareDailyComparisonSnapshot(data, AS_OF, {
        ...SORT,
        key: "unknown",
      } as unknown as DailyComparisonSort),
    ).toThrow();
  });
  it("only enables downloads for a verified result belonging to the current request", () => {
    const data = comparison();
    const ready = renderToStaticMarkup(
      <DailyComparisonExportButton comparison={data} expectedAsOf={AS_OF} sort={SORT} />,
    );
    expect(ready).toContain("下载本次对比 JSON");
    expect(ready).toContain("本次 2 项");
    expect(ready).not.toContain('disabled=""');
    for (const props of [
      { comparison: null },
      { expectedAsOf: undefined },
      { expectedAsOf: "2026-10-26T03:00:00Z" },
    ]) {
      const html = renderToStaticMarkup(
        <DailyComparisonExportButton
          comparison={data}
          expectedAsOf={AS_OF}
          sort={SORT}
          {...props}
        />,
      );
      expect(html).toContain('disabled=""');
      expect(html).toContain("disabled:cursor-not-allowed");
      expect(html).not.toContain("已生成对比快照");
    }
  });
});
