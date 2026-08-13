/**
 * Trading calendar tests.
 *
 * Driven by the same fixtures file as the Python suite
 * (packages/contracts/calendar/fixtures.json) so both calendars stay aligned.
 * Instants are UTC ISO 8601; the calendar interprets them in Asia/Shanghai.
 */

import { describe, expect, it } from "vitest";
import fixtures from "../../calendar/fixtures.json";
import {
  DEFAULT_CALENDAR,
  StaticTradingCalendar,
  type ExchangeId,
  type NonTradingReason,
  type TradingSession,
} from "./trading-calendar";

interface ExpectedSession {
  sessionId: string;
  date: string;
}

interface BoundaryFixture {
  name: string;
  instant: string;
  exchange: ExchangeId;
  expected: ExpectedSession | null;
}

interface NightBoundaryFixture {
  name: string;
  instant: string;
  expected: ExpectedSession | null;
}

interface TradingDayFixture {
  date: string;
  exchange: ExchangeId;
  isTradingDay: boolean;
  reason?: NonTradingReason;
}

interface NextTradingDayFixture {
  date: string;
  exchange: ExchangeId;
  expected: string;
}

const data = fixtures as unknown as {
  boundaries: BoundaryFixture[];
  nightCalendar: { exchange: string; sessions: TradingSession[] };
  nightBoundaries: NightBoundaryFixture[];
  tradingDays: TradingDayFixture[];
  nextTradingDay: NextTradingDayFixture[];
};

describe("sessionAt boundaries", () => {
  it.each(data.boundaries.map((b) => [b.name, b] as const))("%s", (_name, fixture) => {
    const result = DEFAULT_CALENDAR.sessionAt(new Date(fixture.instant), fixture.exchange);
    if (fixture.expected === null) {
      expect(result).toBeNull();
    } else {
      expect(result).not.toBeNull();
      expect(result?.session.sessionId).toBe(fixture.expected.sessionId);
      expect(result?.date).toBe(fixture.expected.date);
    }
  });
});

describe("cross-midnight night calendar", () => {
  const nightCalendar = new StaticTradingCalendar({
    [data.nightCalendar.exchange]: data.nightCalendar.sessions,
  });

  it.each(data.nightBoundaries.map((b) => [b.name, b] as const))("%s", (_name, fixture) => {
    const result = nightCalendar.sessionAt(new Date(fixture.instant), data.nightCalendar.exchange);
    if (fixture.expected === null) {
      expect(result).toBeNull();
    } else {
      expect(result).not.toBeNull();
      expect(result?.session.sessionId).toBe(fixture.expected.sessionId);
      expect(result?.date).toBe(fixture.expected.date);
    }
  });
});

describe("trading days", () => {
  it.each(data.tradingDays.map((d) => [d.date, d.exchange, d] as const))(
    "%s %s",
    (date, exchange, fixture) => {
      expect(DEFAULT_CALENDAR.isTradingDay(date, exchange)).toBe(fixture.isTradingDay);
      const day = DEFAULT_CALENDAR.tradingDay(date, exchange);
      expect(day.isTradingDay).toBe(fixture.isTradingDay);
      if (fixture.reason !== undefined) {
        expect(day.reason).toBe(fixture.reason);
      }
    },
  );
});

describe("next trading day", () => {
  it.each(data.nextTradingDay.map((n) => [n.date, n.exchange, n.expected] as const))(
    "%s %s -> %s",
    (date, exchange, expected) => {
      expect(DEFAULT_CALENDAR.nextTradingDay(date, exchange)).toBe(expected);
    },
  );
});

describe("template integrity", () => {
  it("keeps sessions chronologically ordered per exchange", () => {
    for (const exchange of ["SH", "SZ", "BJ"] as const) {
      const sessions = DEFAULT_CALENDAR.sessionsFor("2026-08-13", exchange);
      expect(sessions.length).toBeGreaterThan(0);
      for (let i = 1; i < sessions.length; i += 1) {
        const prev = sessions[i - 1]!;
        const next = sessions[i]!;
        expect(prev.start <= next.start).toBe(true);
      }
    }
  });

  it("reports every A-share exchange as a trading day on a regular weekday", () => {
    for (const exchange of ["SH", "SZ", "BJ"] as const) {
      expect(DEFAULT_CALENDAR.isTradingDay("2026-08-13", exchange)).toBe(true);
      expect(DEFAULT_CALENDAR.isTradingDay("2026-08-14", exchange)).toBe(true);
    }
  });

  it("never treats a natural day as a trading day on weekends or holidays", () => {
    expect(DEFAULT_CALENDAR.isTradingDay("2026-08-15", "SH")).toBe(false); // Saturday
    expect(DEFAULT_CALENDAR.isTradingDay("2026-08-16", "SH")).toBe(false); // Sunday
    expect(DEFAULT_CALENDAR.isTradingDay("2026-01-01", "SZ")).toBe(false); // New Year
  });
});
