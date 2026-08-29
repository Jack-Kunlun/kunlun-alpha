import type { InstrumentDailyBar } from "@kunlun/shared-types";

interface ParsedDecimal {
  coefficient: bigint;
  scale: number;
}

export interface InstrumentBarsSummary {
  latestClose: string;
  periodChangePercent: string;
  periodHigh: string;
  periodLow: string;
}

function parseDecimal(value: string): ParsedDecimal {
  if (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value)) {
    throw new Error("invalid instrument bar decimal");
  }
  const [whole, fraction = ""] = value.split(".");
  return { coefficient: BigInt(whole + fraction), scale: fraction.length };
}

function aligned(left: ParsedDecimal, right: ParsedDecimal): [bigint, bigint] {
  const scale = Math.max(left.scale, right.scale);
  return [
    left.coefficient * 10n ** BigInt(scale - left.scale),
    right.coefficient * 10n ** BigInt(scale - right.scale),
  ];
}

function compareDecimal(left: string, right: string): number {
  const [leftValue, rightValue] = aligned(parseDecimal(left), parseDecimal(right));
  return leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0;
}

function roundedDivision(numerator: bigint, denominator: bigint): bigint {
  const negative = numerator < 0n;
  const absolute = negative ? -numerator : numerator;
  const rounded = (absolute + denominator / 2n) / denominator;
  return negative ? -rounded : rounded;
}

function periodChange(first: string, last: string): string {
  const [firstValue, lastValue] = aligned(parseDecimal(first), parseDecimal(last));
  if (firstValue === 0n) return "暂无";
  const hundredthsOfPercent = roundedDivision((lastValue - firstValue) * 10_000n, firstValue);
  const sign = hundredthsOfPercent > 0n ? "+" : hundredthsOfPercent < 0n ? "-" : "";
  const absolute = hundredthsOfPercent < 0n ? -hundredthsOfPercent : hundredthsOfPercent;
  return `${sign}${absolute / 100n}.${(absolute % 100n).toString().padStart(2, "0")}%`;
}

export function summarizeInstrumentBars(
  bars: readonly InstrumentDailyBar[],
): InstrumentBarsSummary | null {
  if (bars.length === 0) return null;
  const first = bars[0];
  const last = bars.at(-1);
  if (first === undefined || last === undefined) return null;
  let periodHigh = first.high;
  let periodLow = first.low;
  for (const bar of bars.slice(1)) {
    if (compareDecimal(bar.high, periodHigh) > 0) periodHigh = bar.high;
    if (compareDecimal(bar.low, periodLow) < 0) periodLow = bar.low;
  }
  return {
    latestClose: last.close,
    periodChangePercent: periodChange(first.close, last.close),
    periodHigh,
    periodLow,
  };
}
