import type { InstrumentBarsResponse, InstrumentDailyBar } from "@kunlun/shared-types";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { InstrumentBarsDetails, InstrumentBarsDetailsButton } from "./instrument-bars-details";
import { selectInstrumentBarsPage } from "./instrument-bars-page";

function response(): InstrumentBarsResponse {
  const bars: InstrumentDailyBar[] = Array.from({ length: 23 }, (_, index) => {
    const date = `2026-08-${String(index + 1).padStart(2, "0")}`;
    return {
      date,
      eventTime: `${date}T07:00:00Z`,
      availableTime: `${date}T07:01:00Z`,
      processingTime: `${date}T07:02:00Z`,
      open: "9007199254740993.00000001",
      high: "9007199254740994.00000001",
      low: "9007199254740992.00000001",
      close: "9007199254740993.00000002",
      volume: "100.0000",
      amount: "900719925474099300.00000200",
      suspended: index === 22,
      source: "test-provider",
      sourceVersion: "provider-v1",
      dataVersion: "data-v1",
      evidenceId: `evidence-${date}`,
    };
  });
  return {
    schemaVersion: "instrument-bars-v1",
    dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
    instrumentId: "600519.SH",
    mode: "HISTORICAL",
    requestedAsOf: "2026-08-24T08:00:00.123456789Z",
    effectiveAsOf: "2026-08-24T08:00:00.123456789Z",
    interval: "DAILY",
    priceType: "RAW",
    status: "AVAILABLE",
    barCount: bars.length,
    dataCutoffTime: bars.at(-1)!.eventTime,
    freshnessSeconds: 100,
    bars,
    sourceVersions: ["test-provider@provider-v1"],
    evidenceIds: bars.map((bar) => bar.evidenceId),
  };
}

describe("returned daily window details", () => {
  it("paginates newest first without mutating or rounding the original records", () => {
    const data = response(),
      before = structuredClone(data);
    const first = selectInstrumentBarsPage(data.bars, "", 0);
    const last = selectInstrumentBarsPage(data.bars, "", 99);
    expect(first.rows).toHaveLength(10);
    expect(first.rows[0]).toBe(data.bars[22]);
    expect(first.rows[9]?.date).toBe("2026-08-14");
    expect(first.pageCount).toBe(3);
    expect(last.page).toBe(2);
    expect(last.rows.map((bar) => bar.date)).toEqual(["2026-08-03", "2026-08-02", "2026-08-01"]);
    expect(selectInstrumentBarsPage(data.bars, "", -1).page).toBe(0);
    expect(data).toEqual(before);
  });
  it("finds only exact dates in the returned window and never fills absent dates", () => {
    const data = response();
    const match = selectInstrumentBarsPage(data.bars, "2026-08-13", 3);
    expect(match.rows).toEqual([data.bars[12]]);
    expect(match.page).toBe(0);
    expect(match.matchedCount).toBe(1);
    for (const date of ["2026-08-31", "2026-02-30", "2026-08", " "]) {
      expect(selectInstrumentBarsPage(data.bars, date, 0).rows).toEqual([]);
    }
    expect(selectInstrumentBarsPage([], "", 0)).toEqual({
      rows: [],
      page: 0,
      pageCount: 1,
      matchedCount: 0,
    });
  });
  it("renders exact RAW values, query scope, accessible filters and row provenance", () => {
    const html = renderToStaticMarkup(<InstrumentBarsDetails data={response()} />);
    for (const value of [
      "9007199254740993.00000001",
      "9007199254740993.00000002",
      "100.0000",
      "900719925474099300.00000200",
      "provider-v1",
      "data-v1",
      "evidence-2026-08-23",
      "600519.SH",
      "HISTORICAL",
      "2026-08-24T08:00:00.123456789Z",
      "原始成交量",
      "原始成交额",
      "停牌",
      "查找日期",
      "最新日期在前",
      "仅在本次返回的 23 根日线内查找",
    ])
      expect(html).toContain(value);
    expect(html).toContain('scope="col"');
    expect(html).toMatch(/<button(?=[^>]*aria-label="日线明细上一页")(?=[^>]*disabled="")[^>]*>/);
    expect(html).toMatch(/<button(?=[^>]*aria-label="日线明细下一页")[^>]*>/);
    expect(html).not.toContain("2026-08-13</time>");
    expect(html).toContain('type="date"');
  });
  it("offers a drawer action only for a valid window bound to the current query", () => {
    const data = response();
    const html = renderToStaticMarkup(
      <InstrumentBarsDetailsButton
        data={data}
        instrumentId={data.instrumentId}
        mode={data.mode}
        asOf={data.requestedAsOf}
      />,
    );
    expect(html).toContain("查看明细");
    expect(html).not.toContain('disabled=""');
    expect(html).not.toContain("<table");
    for (const change of [
      { instrumentId: "000001.SZ" },
      { mode: "CURRENT" as const },
      { requestedAsOf: "2026-08-25T08:00:00Z" },
      { barCount: 22 },
      { bars: [data.bars[0]!, data.bars[0]!] },
      {
        bars: data.bars.map((bar, i) =>
          i === 22 ? { ...bar, availableTime: "2026-08-24T08:00:00.123456790Z" } : bar,
        ),
      },
      { evidenceIds: [] },
      { status: "EMPTY" as const },
    ]) {
      const blocked = renderToStaticMarkup(
        <InstrumentBarsDetailsButton
          data={{ ...data, ...change }}
          instrumentId={data.instrumentId}
          mode={data.mode}
          asOf={data.requestedAsOf}
        />,
      );
      expect(blocked).toContain('disabled=""');
      expect(blocked).toContain("日线明细暂不可用");
    }
  });
});
