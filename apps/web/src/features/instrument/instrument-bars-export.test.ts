import type { InstrumentBarsResponse, InstrumentDailyBar } from "@kunlun/shared-types";
import { describe, expect, it } from "vitest";
import { prepareInstrumentBarsCsv } from "./instrument-bars-export";

const HEADERS = [
  "instrumentId",
  "mode",
  "requestedAsOf",
  "effectiveAsOf",
  "dataCutoffTime",
  "interval",
  "priceType",
  "barCount",
  "schemaVersion",
  "dataMeaning",
  "status",
  "freshnessSeconds",
  "date",
  "eventTime",
  "open",
  "high",
  "low",
  "close",
  "volume",
  "amount",
  "suspended",
  "availableTime",
  "processingTime",
  "source",
  "sourceVersion",
  "dataVersion",
  "evidenceId",
];

function bar(date: string, overrides: Partial<InstrumentDailyBar> = {}): InstrumentDailyBar {
  return {
    date,
    eventTime: `${date}T07:00:00.000Z`,
    open: "10.0000",
    high: "11.0000",
    low: "9.0000",
    close: "10.5000",
    volume: "100.000",
    amount: "1000.1200",
    suspended: false,
    availableTime: `${date}T07:01:00.000Z`,
    processingTime: `${date}T07:02:00.000Z`,
    source: "tushare-pro",
    sourceVersion: "vendor-2026.08",
    dataVersion: "bars-v3",
    evidenceId: `evidence-${date}`,
    ...overrides,
  };
}

function response(overrides: Partial<InstrumentBarsResponse> = {}): InstrumentBarsResponse {
  const bars = [bar("2026-08-24"), bar("2026-08-25")];
  return {
    schemaVersion: "instrument-bars-v1",
    dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
    instrumentId: "600519.SH",
    mode: "HISTORICAL",
    requestedAsOf: "2026-08-25T08:00:00.1200Z",
    effectiveAsOf: "2026-08-25T08:00:00.1200Z",
    interval: "DAILY",
    priceType: "RAW",
    status: "AVAILABLE",
    barCount: bars.length,
    dataCutoffTime: bars.at(-1)!.eventTime,
    freshnessSeconds: 60,
    bars,
    sourceVersions: ["tushare-pro@vendor-2026.08"],
    evidenceIds: bars.map((entry) => entry.evidenceId),
    ...overrides,
  };
}

function responseWithUnknownOverrides(
  overrides: Readonly<Record<string, unknown>>,
): InstrumentBarsResponse {
  return { ...response(), ...overrides } as unknown as InstrumentBarsResponse;
}

function parseCsv(csv: string): string[][] {
  const text = csv.startsWith("\uFEFF") ? csv.slice(1) : csv;
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]!;
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
      continue;
    }

    if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\r" && text[index + 1] === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      index += 1;
    } else {
      field += character;
    }
  }

  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

describe("prepareInstrumentBarsCsv", () => {
  it("exports the current returned window in order with exact values and provenance", () => {
    const input = response({
      requestedAsOf: "2026-08-25T16:00:00.1200+08:00",
      effectiveAsOf: "2026-08-25T08:00:00.1200Z",
    });
    const before = structuredClone(input);
    const result = prepareInstrumentBarsCsv(input);
    const rows = parseCsv(result.csv);

    expect(result.filename).toBe("600519.SH-daily-raw-20260825T08000012Z-2.csv");
    expect(result.barCount).toBe(2);
    expect(result.csv.startsWith("\uFEFF")).toBe(true);
    expect(result.csv).toContain("\r\n");
    expect(rows[0]).toEqual(HEADERS);
    expect(rows).toHaveLength(3);
    expect(rows[1]).toEqual([
      "600519.SH",
      "HISTORICAL",
      "2026-08-25T16:00:00.1200+08:00",
      "2026-08-25T08:00:00.1200Z",
      "2026-08-25T07:00:00.000Z",
      "DAILY",
      "RAW",
      "2",
      "instrument-bars-v1",
      "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
      "AVAILABLE",
      "60",
      "2026-08-24",
      "2026-08-24T07:00:00.000Z",
      "10.0000",
      "11.0000",
      "9.0000",
      "10.5000",
      "100.000",
      "1000.1200",
      "false",
      "2026-08-24T07:01:00.000Z",
      "2026-08-24T07:02:00.000Z",
      "tushare-pro",
      "vendor-2026.08",
      "bars-v3",
      "evidence-2026-08-24",
    ]);
    expect(rows[2]?.[12]).toBe("2026-08-25");
    expect(rows[2]?.[20]).toBe("false");
    expect(input).toEqual(before);
  });

  it("keeps a 500-bar export linear instead of repeating the response source-version list", () => {
    const bars = Array.from({ length: 500 }, (_, index) =>
      bar(new Date(Date.UTC(2024, 0, index + 1)).toISOString().slice(0, 10), {
        sourceVersion: `vendor-${index}`,
      }),
    );
    const result = prepareInstrumentBarsCsv(
      response({
        bars,
        barCount: bars.length,
        dataCutoffTime: bars.at(-1)!.eventTime,
        sourceVersions: bars.map((entry) => `tushare-pro@${entry.sourceVersion}`),
        evidenceIds: bars.map((entry) => entry.evidenceId),
      }),
    );
    const rows = parseCsv(result.csv);

    expect(result.barCount).toBe(500);
    expect(rows).toHaveLength(501);
    expect(rows[0]).not.toContain("sourceVersions");
    expect(result.csv.match(/vendor-\d+/g)).toHaveLength(500);
    expect(result.csv.match(/evidence-202/g)).toHaveLength(500);
    expect(rows.slice(1).map((row) => row[24])).toEqual(bars.map((entry) => entry.sourceVersion));
    expect(rows.slice(1).map((row) => row[26])).toEqual(bars.map((entry) => entry.evidenceId));
    expect(result.csv.length).toBeLessThan(400_000);
  });

  it("quotes delimiters, quotes, and line breaks and neutralizes formula-like external text", () => {
    const input = response({
      bars: [
        bar("2026-08-25", {
          source: 'vendor, "desk"\nline 2',
          sourceVersion: " \t=IMPORTXML(1)",
          suspended: true,
        }),
      ],
      barCount: 1,
      dataCutoffTime: "2026-08-25T07:00:00.000Z",
      sourceVersions: ['vendor, "desk"\nline 2@ \t=IMPORTXML(1)'],
      evidenceIds: ["evidence-2026-08-25"],
    });
    const csv = prepareInstrumentBarsCsv(input).csv;
    const rows = parseCsv(csv);

    expect(rows).toHaveLength(2);
    expect(rows[1]?.[20]).toBe("true");
    expect(rows[1]?.[23]).toBe('vendor, "desk"\nline 2');
    expect(rows[1]?.[24]).toBe("' \t=IMPORTXML(1)");
    expect(csv).toContain('"vendor, ""desk""\nline 2"');
    expect(csv).toContain('"\' \t=IMPORTXML(1)"');
  });

  it("preserves a null freshness value and enforces the processing-time point-in-time bound", () => {
    const lastBar = bar("2026-08-25");
    const result = prepareInstrumentBarsCsv(
      response({
        bars: [lastBar],
        barCount: 1,
        dataCutoffTime: lastBar.eventTime,
        freshnessSeconds: null,
        evidenceIds: [lastBar.evidenceId],
      }),
    );
    const rows = parseCsv(result.csv);

    expect(rows[1]?.[11]).toBe("null");
    expect(rows[1]?.[22]).toBe("2026-08-25T07:02:00.000Z");
  });

  it.each<readonly [string, Readonly<Record<string, unknown>>]>([
    ["EMPTY status", { status: "EMPTY" }],
    ["wrong schema", { schemaVersion: "instrument-bars-v2" }],
    ["wrong meaning", { dataMeaning: "EXECUTABLE" }],
    ["wrong interval", { interval: "MINUTE" }],
    ["adjusted prices", { priceType: "ADJUSTED" }],
    ["noncanonical code", { instrumentId: "600519.sh" }],
  ])("rejects unsupported response semantics: %s", (_label, override) => {
    expect(() => prepareInstrumentBarsCsv(responseWithUnknownOverrides(override))).toThrow(
      /日线 CSV/,
    );
  });

  it("rejects empty, oversized, and count-mismatched windows", () => {
    const original = response();
    expect(() => prepareInstrumentBarsCsv(response({ bars: [], barCount: 0 }))).toThrow(/日线 CSV/);
    expect(() => prepareInstrumentBarsCsv(response({ barCount: 1 }))).toThrow(/日线 CSV/);
    const oversized = Array.from({ length: 501 }, (_, index) =>
      bar(new Date(Date.UTC(2025, 0, 1 + index)).toISOString().slice(0, 10)),
    );
    expect(() =>
      prepareInstrumentBarsCsv(
        response({
          bars: oversized,
          barCount: oversized.length,
          dataCutoffTime: oversized.at(-1)!.eventTime,
        }),
      ),
    ).toThrow(/日线 CSV/);
    expect(original.barCount).toBe(2);
  });

  it("turns malformed runtime payloads into a Chinese validation error", () => {
    expect(() => prepareInstrumentBarsCsv(null as unknown as InstrumentBarsResponse)).toThrow(
      /日线 CSV/,
    );

    const malformedBar = null as unknown as InstrumentDailyBar;
    expect(() =>
      prepareInstrumentBarsCsv(
        response({
          bars: [malformedBar],
          barCount: 1,
          dataCutoffTime: "2026-08-25T07:00:00.000Z",
          evidenceIds: ["evidence-2026-08-25"],
        }),
      ),
    ).toThrow(/日线 CSV/);

    const numericAmount = bar("2026-08-25", { amount: 1000 as unknown as string });
    expect(() =>
      prepareInstrumentBarsCsv(
        response({
          bars: [numericAmount],
          barCount: 1,
          dataCutoffTime: numericAmount.eventTime,
          evidenceIds: [numericAmount.evidenceId],
        }),
      ),
    ).toThrow(/日线 CSV/);
  });

  type InvalidDateCase =
    { kind: "date"; date: string } | { kind: "dates"; dates: readonly [string, string] };
  const invalidDateCases: ReadonlyArray<readonly [string, InvalidDateCase]> = [
    ["invalid date", { kind: "date", date: "2026-02-30" }],
    ["unsorted dates", { kind: "dates", dates: ["2026-08-25", "2026-08-24"] }],
    ["duplicate dates", { kind: "dates", dates: ["2026-08-24", "2026-08-24"] }],
  ];

  it.each(invalidDateCases)("rejects invalid bar date order: %s", (_label, testCase) => {
    const bars: InstrumentDailyBar[] =
      testCase.kind === "dates"
        ? testCase.dates.map((date) => bar(date))
        : [bar("2026-08-24", { date: testCase.date }), bar("2026-08-25")];
    expect(() =>
      prepareInstrumentBarsCsv(
        response({
          bars,
          barCount: bars.length,
          dataCutoffTime: bars.at(-1)!.eventTime,
          evidenceIds: bars.map((entry) => entry.evidenceId),
        }),
      ),
    ).toThrow(/日线 CSV/);
  });

  it.each([
    ["missing timezone", "2026-08-25T08:00:00"],
    ["invalid calendar date", "2026-02-30T08:00:00Z"],
    ["invalid time", "2026-08-25T24:00:00Z"],
  ])("rejects invalid point-in-time values: %s", (_label, value) => {
    expect(() => prepareInstrumentBarsCsv(response({ effectiveAsOf: value }))).toThrow(/日线 CSV/);
  });

  it("rejects an effective time after request or bars beyond the effective point", () => {
    expect(() =>
      prepareInstrumentBarsCsv(
        response({
          requestedAsOf: "2026-08-25T07:59:59.000Z",
          effectiveAsOf: "2026-08-25T08:00:00.000Z",
        }),
      ),
    ).toThrow(/日线 CSV/);

    const futureEventBar = bar("2026-08-25", { eventTime: "2026-08-25T08:00:00.121Z" });
    expect(() =>
      prepareInstrumentBarsCsv(
        response({
          bars: [futureEventBar],
          barCount: 1,
          dataCutoffTime: futureEventBar.eventTime,
          evidenceIds: [futureEventBar.evidenceId],
        }),
      ),
    ).toThrow(/日线 CSV/);

    const futureBar = bar("2026-08-25", { availableTime: "2026-08-25T08:00:00.121Z" });
    expect(() =>
      prepareInstrumentBarsCsv(
        response({
          bars: [futureBar],
          barCount: 1,
          dataCutoffTime: futureBar.eventTime,
          evidenceIds: [futureBar.evidenceId],
        }),
      ),
    ).toThrow(/日线 CSV/);

    const futureProcessingBar = bar("2026-08-25", {
      processingTime: "2026-08-25T08:00:00.121Z",
    });
    expect(() =>
      prepareInstrumentBarsCsv(
        response({
          bars: [futureProcessingBar],
          barCount: 1,
          dataCutoffTime: futureProcessingBar.eventTime,
          evidenceIds: [futureProcessingBar.evidenceId],
        }),
      ),
    ).toThrow(/日线 CSV/);
  });

  it("requires the declared cutoff to equal the final bar event time", () => {
    expect(() =>
      prepareInstrumentBarsCsv(response({ dataCutoffTime: "2026-08-25T06:59:59Z" })),
    ).toThrow(/日线 CSV/);
  });

  it.each(["-1.00", "+1.00", "1e3", "NaN", ""])(
    "rejects a non-nonnegative-decimal bar value: %s",
    (value) => {
      const first = bar("2026-08-24", { close: value });
      const second = bar("2026-08-25");
      expect(() =>
        prepareInstrumentBarsCsv(
          response({
            bars: [first, second],
            barCount: 2,
            dataCutoffTime: second.eventTime,
            evidenceIds: [first.evidenceId, second.evidenceId],
          }),
        ),
      ).toThrow(/日线 CSV/);
    },
  );

  it("rejects missing top-level and per-bar provenance", () => {
    const barWithoutSource = bar("2026-08-25", { evidenceId: "  " });
    expect(() => prepareInstrumentBarsCsv(response({ sourceVersions: [] }))).toThrow(/日线 CSV/);
    expect(() => prepareInstrumentBarsCsv(response({ evidenceIds: [] }))).toThrow(/日线 CSV/);
    expect(() =>
      prepareInstrumentBarsCsv(
        response({
          bars: [barWithoutSource],
          barCount: 1,
          dataCutoffTime: barWithoutSource.eventTime,
          evidenceIds: ["evidence-2026-08-25"],
        }),
      ),
    ).toThrow(/日线 CSV/);
  });

  it.each<readonly [string, Partial<InstrumentBarsResponse>]>([
    ["undeclared source", { sourceVersions: ["another-provider@vendor-2026.08"] }],
    ["undeclared version", { sourceVersions: ["tushare-pro@another-version"] }],
    ["undeclared evidence", { evidenceIds: ["unrelated-evidence"] }],
    [
      "extra source version",
      { sourceVersions: ["tushare-pro@vendor-2026.08", "another-provider@unused"] },
    ],
    [
      "extra evidence",
      { evidenceIds: ["evidence-2026-08-24", "evidence-2026-08-25", "unused-evidence"] },
    ],
  ])("rejects inconsistent aggregate provenance: %s", (_label, overrides) => {
    expect(() => prepareInstrumentBarsCsv(response(overrides))).toThrow(/溯源.*不一致/);
  });
});
