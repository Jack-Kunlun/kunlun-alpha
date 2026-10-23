import { describe, expect, it } from "vitest";
import { LOCAL_TERMINAL_STOCKS } from "../instrument/local-terminal-stock-samples";
import {
  buildDailyComparison,
  formatDailyComparisonChange,
  formatDailyComparisonDecimal,
  sortDailyComparisonRows,
  type DailyComparisonOutcome,
} from "./daily-comparison";

const AS_OF = "2026-10-16T16:00:00.000Z";

function bar(
  date: string,
  close: string,
  amount: string,
  options: {
    source?: string;
    sourceVersion?: string;
    dataVersion?: string;
    suspended?: boolean;
    eventTime?: string;
    availableTime?: string;
    processingTime?: string;
  } = {},
) {
  return {
    date,
    eventTime: options.eventTime ?? `${date}T07:00:00.000Z`,
    open: close,
    high: close,
    low: close,
    close,
    volume: "100",
    amount,
    suspended: options.suspended ?? false,
    availableTime: options.availableTime ?? `${date}T08:00:00.000Z`,
    processingTime: options.processingTime ?? `${date}T08:01:00.000Z`,
    source: options.source ?? "akshare-eastmoney",
    sourceVersion: options.sourceVersion ?? "2026.08.29",
    dataVersion: options.dataVersion ?? "daily-bars-v2",
    evidenceId: `evidence-${date}`,
  };
}

function response(instrumentId: string, bars: unknown[], overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: "instrument-bars-v1",
    dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
    instrumentId,
    mode: "HISTORICAL",
    requestedAsOf: AS_OF,
    effectiveAsOf: AS_OF,
    interval: "DAILY",
    priceType: "RAW",
    status: bars.length === 0 ? "EMPTY" : "AVAILABLE",
    barCount: bars.length,
    dataCutoffTime: null,
    freshnessSeconds: null,
    bars,
    sourceVersions: ["daily-bars-v2"],
    evidenceIds: [],
    ...overrides,
  };
}

function outcome(instrumentId: string, payload: unknown): DailyComparisonOutcome {
  const stock = LOCAL_TERMINAL_STOCKS.find((item) => item.instrumentId === instrumentId);
  if (stock === undefined) throw new Error(`unknown test instrument: ${instrumentId}`);
  return { stock, kind: "response", value: payload };
}

describe("daily comparison model", () => {
  it("aligns on the latest available date and computes only against one shared prior date", () => {
    const outcomes: DailyComparisonOutcome[] = [
      outcome(
        "000001.SZ",
        response("000001.SZ", [
          bar("2026-10-15", "100.00", "9007199254740993.25"),
          bar("2026-10-16", "101.005", "9007199254740994.25"),
        ]),
      ),
      outcome(
        "002594.SZ",
        response("002594.SZ", [
          bar("2026-10-14", "50.00", "200"),
          bar("2026-10-16", "51.00", "300"),
        ]),
      ),
      outcome("300750.SZ", response("300750.SZ", [bar("2026-10-15", "40.00", "400")])),
      outcome(
        "301236.SZ",
        response("301236.SZ", [
          bar("2026-10-15", "20.00", "500"),
          bar("2026-10-16", "19.00", "600", { sourceVersion: "other-version" }),
        ]),
      ),
      outcome(
        "600000.SH",
        response("600000.SH", [bar("2026-10-15", "0", "700"), bar("2026-10-16", "1.00", "800")]),
      ),
      outcome(
        "600519.SH",
        response("600519.SH", [
          bar("2026-10-15", "100.00", "900"),
          bar("2026-10-16", "99.00", "1000", { suspended: true }),
        ]),
      ),
      outcome("601318.SH", response("601318.SH", [])),
      { stock: LOCAL_TERMINAL_STOCKS[7], kind: "forbidden" },
    ];

    const comparison = buildDailyComparison(AS_OF, outcomes);

    expect(comparison.comparisonDate).toBe("2026-10-16");
    expect(comparison.baselineDate).toBe("2026-10-15");
    expect(comparison.rows[0]).toMatchObject({
      status: "AVAILABLE",
      latest: { close: "101.005", amount: "9007199254740994.25" },
      changeHundredthsOfPercent: 101n,
      changeReason: null,
    });
    expect(comparison.rows[1]).toMatchObject({
      status: "AVAILABLE",
      changeHundredthsOfPercent: null,
      changeReason: "基准日期不一致",
    });
    expect(comparison.rows[2]).toMatchObject({
      status: "AVAILABLE",
      latest: { date: "2026-10-15" },
      changeReason: "行情日期不一致",
    });
    expect(comparison.rows[3]?.changeReason).toBe("来源版本不一致");
    expect(comparison.rows[4]?.changeReason).toBe("前收价无效");
    expect(comparison.rows[5]?.changeReason).toBe("停牌，不计算涨跌幅");
    expect(comparison.rows[6]?.status).toBe("EMPTY");
    expect(comparison.rows[7]?.status).toBe("FORBIDDEN");
  });

  it("rejects mismatched identities, future point-in-time fields, non-RAW data, and bad bar order", () => {
    const validBars = [bar("2026-10-15", "10.00", "100"), bar("2026-10-16", "11.00", "200")];
    const invalidPayloads = [
      response("600519.SH", validBars),
      response("000001.SZ", [
        validBars[0],
        bar("2026-10-16", "11.00", "200", { eventTime: "2026-10-17T01:00:00.000Z" }),
      ]),
      response("000001.SZ", [
        validBars[0],
        bar("2026-10-16", "11.00", "200", { availableTime: "2026-10-17T01:00:00.000Z" }),
      ]),
      response("000001.SZ", [
        validBars[0],
        bar("2026-10-16", "11.00", "200", { processingTime: "2026-10-17T01:00:00.000Z" }),
      ]),
      response("000001.SZ", validBars, { priceType: "FORWARD_ADJUSTED" }),
      response("000001.SZ", [...validBars].reverse()),
      response("000001.SZ", [bar("2026-10-16", "1e3", "200")]),
    ];

    for (const payload of invalidPayloads) {
      const comparison = buildDailyComparison(AS_OF, [outcome("000001.SZ", payload)]);
      expect(comparison.rows[0]?.status).toBe("INVALID");
    }

    const sourceMismatch = buildDailyComparison(AS_OF, [
      outcome(
        "000001.SZ",
        response("000001.SZ", [
          bar("2026-10-15", "10.00", "100"),
          bar("2026-10-16", "11.00", "200", { source: "other-source" }),
        ]),
      ),
    ]);
    expect(sourceMismatch.rows[0]).toMatchObject({
      status: "AVAILABLE",
      changeHundredthsOfPercent: null,
      changeReason: "来源版本不一致",
    });
  });

  it("requires the returned effective point-in-time to match the fixed cohort", () => {
    const payload = response("000001.SZ", [bar("2026-10-16", "11.00", "200")], {
      effectiveAsOf: "2026-10-16T15:59:59.999Z",
    });

    const comparison = buildDailyComparison(AS_OF, [outcome("000001.SZ", payload)]);

    expect(comparison.rows[0]?.status).toBe("INVALID");
  });

  it.each([
    "2026-02-30T07:00:00.000Z",
    "2026-10-15T24:00:00Z",
    "2026-10-15T07:00:00-00:00",
    "2026-10-15T07:00:00.1234567890Z",
  ])("rejects non-canonical RFC3339 timestamps: %s", (eventTime) => {
    const payload = response("000001.SZ", [bar("2026-10-16", "11.00", "200", { eventTime })]);

    const comparison = buildDailyComparison(AS_OF, [outcome("000001.SZ", payload)]);

    expect(comparison.rows[0]?.status).toBe("INVALID");
  });

  it("rejects daily bars whose Shanghai trading date is after the fixed cutoff", () => {
    const cutoff = "2026-10-16T15:59:59.999Z";
    const futureDate = response(
      "000001.SZ",
      [
        bar("2026-10-17", "11.00", "200", {
          eventTime: "2026-10-16T15:00:00.000Z",
          availableTime: "2026-10-16T15:01:00.000Z",
          processingTime: "2026-10-16T15:02:00.000Z",
        }),
      ],
      { requestedAsOf: cutoff, effectiveAsOf: cutoff },
    );
    const sameShanghaiDate = response(
      "002594.SZ",
      [
        bar("2026-10-16", "11.00", "200", {
          eventTime: "2026-10-16T15:00:00.000Z",
          availableTime: "2026-10-16T15:01:00.000Z",
          processingTime: "2026-10-16T15:02:00.000Z",
        }),
      ],
      { requestedAsOf: cutoff, effectiveAsOf: cutoff },
    );

    const comparison = buildDailyComparison(cutoff, [
      outcome("000001.SZ", futureDate),
      outcome("002594.SZ", sameShanghaiDate),
    ]);

    expect(comparison.rows[0]?.status).toBe("INVALID");
    expect(comparison.rows[1]?.status).toBe("AVAILABLE");
  });

  it("requires matching data versions before calculating a change", () => {
    const comparison = buildDailyComparison(AS_OF, [
      outcome(
        "000001.SZ",
        response("000001.SZ", [
          bar("2026-10-15", "10.00", "100"),
          bar("2026-10-16", "11.00", "200", { dataVersion: "daily-bars-v3" }),
        ]),
      ),
    ]);

    expect(comparison.rows[0]).toMatchObject({
      status: "AVAILABLE",
      latest: { close: "11.00", amount: "200", dataVersion: "daily-bars-v3" },
      previous: { close: "10.00", dataVersion: "daily-bars-v2" },
      changeHundredthsOfPercent: null,
      changeReason: "数据版本不一致",
    });
  });

  it("keeps failed and empty rows explicit and isolates them from numeric sorting", () => {
    const comparison = buildDailyComparison(AS_OF, [
      outcome(
        "000001.SZ",
        response("000001.SZ", [
          bar("2026-10-15", "9007199254740993.10", "9007199254740993.10"),
          bar("2026-10-16", "9007199254740993.20", "9007199254740993.20"),
        ]),
      ),
      outcome(
        "002594.SZ",
        response("002594.SZ", [
          bar("2026-10-15", "9007199254740993.30", "9007199254740993.30"),
          bar("2026-10-16", "9007199254740993.40", "9007199254740993.40"),
        ]),
      ),
      outcome(
        "300750.SZ",
        response("300750.SZ", [bar("2026-10-15", "99999999999999999", "99999999999999999")]),
      ),
      { stock: LOCAL_TERMINAL_STOCKS[3], kind: "error" },
      ...LOCAL_TERMINAL_STOCKS.slice(4).map((stock) => ({
        stock,
        kind: "response" as const,
        value: response(stock.instrumentId, []),
      })),
    ]);

    expect(
      sortDailyComparisonRows(comparison, { key: "close", direction: "descending" }).map(
        (row) => row.instrumentId,
      ),
    ).toEqual([
      "002594.SZ",
      "000001.SZ",
      "300750.SZ",
      "301236.SZ",
      "600000.SH",
      "600519.SH",
      "601318.SH",
      "688981.SH",
    ]);
    expect(
      sortDailyComparisonRows(comparison, { key: "amount", direction: "ascending" })
        .map((row) => row.instrumentId)
        .slice(0, 3),
    ).toEqual(["000001.SZ", "002594.SZ", "300750.SZ"]);
    expect(comparison.rows[3]?.status).toBe("ERROR");
  });

  it("formats precise values and rounds signed percentage changes to two places", () => {
    expect(formatDailyComparisonDecimal("9007199254740993.25")).toBe("9,007,199,254,740,993.25");
    expect(formatDailyComparisonChange(101n)).toBe("+1.01%");
    expect(formatDailyComparisonChange(-101n)).toBe("-1.01%");
    expect(formatDailyComparisonChange(null)).toBe("—");
  });
});
