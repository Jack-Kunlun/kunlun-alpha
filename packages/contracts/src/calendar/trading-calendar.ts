/**
 * A-share trading calendar.
 *
 * Normalizes trading days, sessions, holidays and temporary closures into one
 * queryable calendar. Times are local clock HH:MM in Asia/Shanghai; sessions
 * are half-open [start, end). A session that crosses midnight (start > end,
 * e.g. a night session 21:00 -> 02:30) belongs to the trading day on which it
 * starts. The default templates and seed holidays come from
 * packages/contracts/calendar/ — the single source of truth shared with the
 * Python port in market-core.
 */

import sessionTemplates from "../../calendar/session-templates.json";
import holidaysJson from "../../calendar/holidays.json";

export type ExchangeId = "SH" | "SZ" | "BJ";
export type SessionKind = "CONTINUOUS" | "OPEN_AUCTION" | "CLOSE_AUCTION" | "BREAK" | "NIGHT";
export type HolidayReason = "PUBLIC_HOLIDAY" | "TEMPORARY_CLOSURE" | "SPECIAL";
export type NonTradingReason = "WEEKEND" | HolidayReason;

export interface TradingSession {
  /** Stable machine id, e.g. open-auction / morning / lunch-break / afternoon. */
  sessionId: string;
  kind: SessionKind;
  /** Local clock HH:MM (Asia/Shanghai), inclusive start. */
  start: string;
  /** Local clock HH:MM (Asia/Shanghai), exclusive end. */
  end: string;
  exchange: ExchangeId;
  /** True when the session ends after midnight (start > end). */
  crossesMidnight?: boolean;
}

export interface TradingDay {
  /** ISO 8601 calendar date in Asia/Shanghai. */
  date: string;
  exchange: ExchangeId;
  isTradingDay: boolean;
  reason?: NonTradingReason;
  note?: string;
}

export interface Holiday {
  date: string;
  exchange: ExchangeId;
  reason: HolidayReason;
  note?: string;
}

export interface SessionAtResult {
  session: TradingSession;
  /** The trading day the session belongs to (may be the previous calendar day). */
  date: string;
}

export interface TradingCalendar {
  /** Sessions that apply to a given trading day; empty when not a trading day. */
  sessionsFor(date: string, exchange: ExchangeId): TradingSession[];
  /** Whether the date is a trading day for the exchange (weekends/holidays are never trading days). */
  isTradingDay(date: string, exchange: ExchangeId): boolean;
  /** The per-date status record for an exchange. */
  tradingDay(date: string, exchange: ExchangeId): TradingDay;
  /** The session containing a given instant, if any. */
  sessionAt(instant: Date, exchange: ExchangeId): SessionAtResult | null;
  /** The first trading day strictly after the given date. */
  nextTradingDay(date: string, exchange: ExchangeId): string;
}

const DEFAULT_TEMPLATES = sessionTemplates as unknown as {
  timezone: string;
  exchanges: Record<ExchangeId, { sessions: TradingSession[] }>;
};
const DEFAULT_HOLIDAYS = holidaysJson as unknown as { timezone: string; holidays: Holiday[] };

export const MARKET_TIMEZONE = "Asia/Shanghai";

const LOCAL_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: MARKET_TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function toLocalParts(instant: Date): { date: string; time: string } {
  const parts = LOCAL_FORMATTER.formatToParts(instant);
  const get = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((p) => p.type === type)?.value ?? "";
  return {
    date: `${get("year")}-${get("month")}-${get("day")}`,
    time: `${get("hour")}:${get("minute")}:${get("second")}`,
  };
}

/** "HH:MM" -> minutes since local midnight. */
function toMinutes(clock: string): number {
  const [h, m] = clock.split(":");
  return Number(h) * 60 + Number(m);
}

function addDays(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function weekday(date: string): number {
  // 0 = Sunday, 6 = Saturday.
  return new Date(`${date}T00:00:00Z`).getUTCDay();
}

function isWeekend(date: string): boolean {
  const w = weekday(date);
  return w === 0 || w === 6;
}

/**
 * Whether a local clock time falls inside a session. Cross-midnight sessions
 * cover [start, 24:00) ∪ [00:00, end) of the same (start) trading day.
 */
function inSession(session: TradingSession, minutes: number): boolean {
  const start = toMinutes(session.start);
  const end = toMinutes(session.end);
  if (session.crossesMidnight || start > end) {
    return minutes >= start || minutes < end;
  }
  return minutes >= start && minutes < end;
}

/**
 * Default in-memory calendar built from the shared templates and seed holidays.
 * Real provider-synced calendars (P1-N07) will implement the same interface.
 */
export class StaticTradingCalendar implements TradingCalendar {
  private readonly templates: Record<string, TradingSession[]>;
  private readonly holidaysByKey: Map<string, Holiday>;

  constructor(
    templates: Record<string, TradingSession[]> = Object.fromEntries(
      Object.entries(DEFAULT_TEMPLATES.exchanges).map(([exchange, t]) => [exchange, t.sessions]),
    ),
    holidays: Holiday[] = DEFAULT_HOLIDAYS.holidays,
  ) {
    this.templates = templates;
    this.holidaysByKey = new Map(holidays.map((h) => [`${h.date}:${h.exchange}`, h]));
  }

  sessionsFor(date: string, exchange: string): TradingSession[] {
    return this.isTradingDay(date, exchange) ? (this.templates[exchange] ?? []) : [];
  }

  isTradingDay(date: string, exchange: string): boolean {
    return !isWeekend(date) && !this.holidaysByKey.has(`${date}:${exchange}`);
  }

  tradingDay(date: string, exchange: string): TradingDay {
    const holiday = this.holidaysByKey.get(`${date}:${exchange}`);
    const exchangeId = exchange as ExchangeId;
    if (holiday) {
      return { date, exchange: exchangeId, isTradingDay: false, reason: holiday.reason, note: holiday.note };
    }
    if (isWeekend(date)) {
      return { date, exchange: exchangeId, isTradingDay: false, reason: "WEEKEND" };
    }
    return { date, exchange: exchangeId, isTradingDay: true };
  }

  sessionAt(instant: Date, exchange: string): SessionAtResult | null {
    const { date, time } = toLocalParts(instant);
    const minutes = toMinutes(time.slice(0, 5));

    const sessions = this.templates[exchange] ?? [];
    // A cross-midnight session belongs to its start trading day: the evening
    // part [start, 24:00) matches the start day, while the early morning part
    // [00:00, end) is matched by the *previous* day's session below.
    if (this.isTradingDay(date, exchange)) {
      for (const session of sessions) {
        const crossesMidnight = session.crossesMidnight || toMinutes(session.start) > toMinutes(session.end);
        if (crossesMidnight) {
          if (minutes >= toMinutes(session.start)) {
            return { session, date };
          }
        } else if (inSession(session, minutes)) {
          return { session, date };
        }
      }
    }

    const yesterday = addDays(date, -1);
    if (this.isTradingDay(yesterday, exchange)) {
      for (const session of sessions) {
        const crossesMidnight = session.crossesMidnight || toMinutes(session.start) > toMinutes(session.end);
        if (crossesMidnight && minutes < toMinutes(session.end)) {
          return { session, date: yesterday };
        }
      }
    }
    return null;
  }

  nextTradingDay(date: string, exchange: string): string {
    let candidate = addDays(date, 1);
    for (let guard = 0; guard < 366; guard += 1) {
      if (this.isTradingDay(candidate, exchange)) {
        return candidate;
      }
      candidate = addDays(candidate, 1);
    }
    throw new Error(`No trading day found within 365 days after ${date}`);
  }
}

/** The default A-share calendar (SH/SZ/BJ session templates + seed holidays). */
export const DEFAULT_CALENDAR: TradingCalendar = new StaticTradingCalendar();
