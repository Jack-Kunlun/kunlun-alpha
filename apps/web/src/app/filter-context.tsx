import { createContext, type PropsWithChildren, useCallback, useContext, useMemo } from "react";
import { useLocation, useNavigate } from "react-router";

const SECURITY_ID = /^[0-9]{6}\.(?:SH|SZ|BJ)$/;
const RFC3339_WITH_ZONE =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|([+-])(\d{2}):(\d{2}))$/;

export interface TerminalFilterContextV1 {
  version: "v1";
  asOf: string | null;
  instrumentIds: readonly string[];
}

export interface ParsedTerminalFilters {
  value: TerminalFilterContextV1;
  rejected: readonly string[];
}

interface TerminalFilterContextValue extends ParsedTerminalFilters {
  hrefForRoute: (path: string) => string;
  replaceFilters: (next: TerminalFilterContextV1) => void;
}

export const EMPTY_TERMINAL_FILTERS: TerminalFilterContextV1 = {
  version: "v1",
  asOf: null,
  instrumentIds: [],
};

function canonicalAsOf(raw: string): string | null {
  const match = RFC3339_WITH_ZONE.exec(raw);
  if (match === null) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const fraction = match[7] ?? "";
  const offsetSign = match[9];
  const offsetHour = Number(match[10] ?? 0);
  const offsetMinute = Number(match[11] ?? 0);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

  if (
    year === 0 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > (daysInMonth[month - 1] ?? 0) ||
    hour > 23 ||
    minute > 59 ||
    second > 59 ||
    offsetHour > 23 ||
    offsetMinute > 59
  ) {
    return null;
  }

  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, Number(`${fraction}000`.slice(0, 3)));
  const unsignedOffsetMinutes = offsetHour * 60 + offsetMinute;
  const offsetMinutes = offsetSign === "+" ? unsignedOffsetMinutes : -unsignedOffsetMinutes;
  const timestamp = date.getTime() - offsetMinutes * 60_000;
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : null;
}

export function parseTerminalFilters(search: string): ParsedTerminalFilters {
  const params = new URLSearchParams(search);
  const rejected: string[] = [];
  const rawAsOf = params.get("asOf");
  const asOf = rawAsOf === null ? null : canonicalAsOf(rawAsOf);
  if (rawAsOf !== null && asOf === null) rejected.push("asOf");

  const instrumentIds = [
    ...new Set(params.getAll("instrument").map((value) => value.toUpperCase())),
  ]
    .filter((value) => {
      const valid = SECURITY_ID.test(value);
      if (!valid) rejected.push(`instrument:${value}`);
      return valid;
    })
    .sort();

  return {
    value: { version: "v1", asOf, instrumentIds },
    rejected,
  };
}

export function serializeTerminalFilters(filters: TerminalFilterContextV1): string {
  const params = new URLSearchParams();
  if (filters.asOf !== null) {
    const asOf = canonicalAsOf(filters.asOf);
    if (asOf === null) throw new Error("Terminal filter asOf must be timezone-aware RFC3339");
    params.set("asOf", asOf);
  }
  for (const instrumentId of [...new Set(filters.instrumentIds)].sort()) {
    const normalized = instrumentId.toUpperCase();
    if (!SECURITY_ID.test(normalized)) {
      throw new Error(`Terminal filter instrumentId is invalid: ${instrumentId}`);
    }
    params.append("instrument", normalized);
  }
  return params.toString();
}

export function withTerminalFilters(path: string, filters: TerminalFilterContextV1): string {
  const search = serializeTerminalFilters(filters);
  return search ? `${path}?${search}` : path;
}

const TerminalFilterContext = createContext<TerminalFilterContextValue>({
  value: EMPTY_TERMINAL_FILTERS,
  rejected: [],
  hrefForRoute: (path) => path,
  replaceFilters: () => undefined,
});

export function TerminalFilterProvider({ children }: PropsWithChildren) {
  const location = useLocation();
  const navigate = useNavigate();
  const parsed = useMemo(() => parseTerminalFilters(location.search), [location.search]);
  const hrefForRoute = useCallback(
    (path: string) => withTerminalFilters(path, parsed.value),
    [parsed.value],
  );
  const replaceFilters = useCallback(
    (next: TerminalFilterContextV1) => {
      const search = serializeTerminalFilters(next);
      void navigate(
        { pathname: location.pathname, search: search ? `?${search}` : "" },
        { replace: true },
      );
    },
    [location.pathname, navigate],
  );
  const value = useMemo<TerminalFilterContextValue>(
    () => ({ ...parsed, hrefForRoute, replaceFilters }),
    [hrefForRoute, parsed, replaceFilters],
  );
  return <TerminalFilterContext.Provider value={value}>{children}</TerminalFilterContext.Provider>;
}

export function useTerminalFilters(): TerminalFilterContextValue {
  return useContext(TerminalFilterContext);
}
