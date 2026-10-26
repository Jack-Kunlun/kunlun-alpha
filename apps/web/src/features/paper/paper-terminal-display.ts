import type { PaperTerminalPosition, PaperTerminalWorkspace } from "@kunlun/shared-types";

type PersistenceMode = PaperTerminalWorkspace["persistenceMode"];
type PositionDisplay = Pick<
  PaperTerminalPosition,
  "instrumentId" | "quantity" | "availableQuantity" | "costAmount"
>;
interface ParsedInstant {
  seconds: bigint;
  fraction: string;
}

export interface PaperTerminalAccountDisplay {
  name: string;
  status: "ACTIVE" | "SUSPENDED" | "CLOSED";
  baseCurrency: "CNY";
  initialCapital: string;
  cash: string;
  dataCutoffTime: string;
  eventCount: number;
  positions: PositionDisplay[];
}

export type PaperTerminalDisplay =
  | { kind: "empty"; persistenceMode: PersistenceMode }
  | {
      kind: "account";
      persistenceMode: PersistenceMode;
      workspaceStatus: "READY" | "DEGRADED";
      generatedAt: string;
      account: PaperTerminalAccountDisplay;
    }
  | { kind: "invalid"; message: string };

export function formatPaperLedgerTime(value: string): string {
  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(instant);
}

/** Compare validated ledger timestamps without discarding sub-millisecond precision. */
export function comparePaperLedgerTimes(left: string, right: string): number {
  const a = parseTimestamp(left);
  const b = parseTimestamp(right);
  if (a === null || b === null) throw new Error("账本时间格式无效");
  return compareInstants(a, b);
}

const MONEY = /^(?:0|[1-9]\d*)(?:\.\d*[1-9])?$/;
const INSTRUMENT_ID = /^\d{6}\.(?:SH|SZ|BJ)$/;
const TIMESTAMP =
  /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?([Zz]|([+-])(\d{2}):(\d{2}))$/;

export function parsePaperTerminalDisplay(value: unknown): PaperTerminalDisplay {
  if (!isRecord(value)) return invalid("账户账本响应无效。");
  if (
    value.schemaVersion !== "paper-terminal-workspace-v1" ||
    value.dataMeaning !== "SIMULATION_ONLY_NO_BROKER_PATH" ||
    value.executionCapability !== "PAPER_ONLY"
  ) {
    return invalid("账户账本能力标识无效。");
  }
  if (
    value.persistenceMode !== "VOLATILE_IN_MEMORY" &&
    value.persistenceMode !== "DURABLE_COMMAND_JOURNAL"
  ) {
    return invalid("账户账本持久化状态无效。");
  }
  if (
    !Array.isArray(value.limitations) ||
    value.limitations.length === 0 ||
    !value.limitations.every(isNonEmptyString)
  ) {
    return invalid("账户账本能力说明无效。");
  }

  const generatedAt = parseTimestamp(value.generatedAt);
  if (generatedAt === null) return invalid("工作区生成时间格式无效。");

  const persistenceMode = value.persistenceMode;
  if (value.status === "EMPTY") {
    return value.account === null
      ? { kind: "empty", persistenceMode }
      : invalid("空账本不应包含账户数据。");
  }
  if (value.status !== "READY" && value.status !== "DEGRADED") {
    return invalid("账户账本状态无效。");
  }
  if (!isRecord(value.account)) return invalid("账户账本数据无效：账户缺失。");

  const account = value.account;
  if (
    !isNonEmptyString(account.name) ||
    account.name.length > 80 ||
    (account.status !== "ACTIVE" &&
      account.status !== "SUSPENDED" &&
      account.status !== "CLOSED") ||
    account.baseCurrency !== "CNY"
  ) {
    return invalid("账户账本数据无效：账户信息格式错误。");
  }
  if (!isNonNegativeMoney(account.initialCapital) || !isNonNegativeMoney(account.cash)) {
    return invalid("账户账本数据无效：金额格式错误。");
  }
  if (!Number.isSafeInteger(account.eventCount) || (account.eventCount as number) < 1) {
    return invalid("账户账本数据无效：事件数量格式错误。");
  }
  const dataCutoffTime = parseTimestamp(account.dataCutoffTime);
  if (dataCutoffTime === null) return invalid("账户账本数据无效：截止时间格式错误。");
  if (compareInstants(dataCutoffTime, generatedAt) > 0) {
    return invalid("账户账本数据无效：截止时间晚于工作区生成时间。");
  }
  if (!Array.isArray(account.positions)) {
    return invalid("账户账本数据无效：持仓列表格式错误。");
  }

  const seenInstruments = new Set<string>();
  const positions: PositionDisplay[] = [];
  for (const position of account.positions) {
    if (!isRecord(position) || typeof position.instrumentId !== "string") {
      return invalid("账户账本数据无效：持仓格式错误。");
    }
    if (!INSTRUMENT_ID.test(position.instrumentId) || seenInstruments.has(position.instrumentId)) {
      return invalid("账户账本数据无效：证券代码格式错误或重复。");
    }
    if (
      !Number.isSafeInteger(position.quantity) ||
      !Number.isSafeInteger(position.availableQuantity) ||
      (position.quantity as number) < 0 ||
      (position.availableQuantity as number) < 0 ||
      (position.availableQuantity as number) > (position.quantity as number)
    ) {
      return invalid("账户账本数据无效：持仓数量格式错误。");
    }
    if (!isNonNegativeMoney(position.costAmount)) {
      return invalid("账户账本数据无效：持仓成本格式错误。");
    }

    seenInstruments.add(position.instrumentId);
    positions.push({
      instrumentId: position.instrumentId,
      quantity: position.quantity as number,
      availableQuantity: position.availableQuantity as number,
      costAmount: position.costAmount,
    });
  }

  return {
    kind: "account",
    persistenceMode,
    workspaceStatus: value.status as "READY" | "DEGRADED",
    generatedAt: value.generatedAt as string,
    account: {
      name: account.name,
      status: account.status,
      baseCurrency: account.baseCurrency,
      initialCapital: account.initialCapital,
      cash: account.cash,
      dataCutoffTime: account.dataCutoffTime as string,
      eventCount: account.eventCount as number,
      positions,
    },
  };
}

function parseTimestamp(value: unknown): ParsedInstant | null {
  if (typeof value !== "string") return null;
  const match = TIMESTAMP.exec(value);
  if (match === null) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const fraction = match[7] ?? "";
  if (
    year < 1 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > daysInMonth(year, month) ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    return null;
  }

  let offsetMinutes = 0;
  if (match[8]?.toUpperCase() !== "Z") {
    const offsetHour = Number(match[10]);
    const offsetMinute = Number(match[11]);
    if (offsetHour > 23 || offsetMinute > 59) return null;
    offsetMinutes = (match[9] === "+" ? 1 : -1) * (offsetHour * 60 + offsetMinute);
  }

  const localSeconds =
    daysFromCivil(year, month, day) * 86_400 + hour * 3_600 + minute * 60 + second;
  return { seconds: BigInt(localSeconds - offsetMinutes * 60), fraction };
}

function compareInstants(left: ParsedInstant, right: ParsedInstant): number {
  if (left.seconds < right.seconds) return -1;
  if (left.seconds > right.seconds) return 1;
  const scale = Math.max(left.fraction.length, right.fraction.length);
  const leftFraction = left.fraction.padEnd(scale, "0");
  const rightFraction = right.fraction.padEnd(scale, "0");
  return leftFraction < rightFraction ? -1 : leftFraction > rightFraction ? 1 : 0;
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return isLeapYear(year) ? 29 : 28;
  return month === 4 || month === 6 || month === 9 || month === 11 ? 30 : 31;
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysFromCivil(year: number, month: number, day: number): number {
  const adjustedYear = year - (month <= 2 ? 1 : 0);
  const era = Math.floor(adjustedYear / 400);
  const yearOfEra = adjustedYear - era * 400;
  const shiftedMonth = month + (month > 2 ? -3 : 9);
  const dayOfYear = Math.floor((153 * shiftedMonth + 2) / 5) + day - 1;
  const dayOfEra =
    yearOfEra * 365 + Math.floor(yearOfEra / 4) - Math.floor(yearOfEra / 100) + dayOfYear;
  return era * 146_097 + dayOfEra - 719_468;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isNonNegativeMoney(value: unknown): value is string {
  return typeof value === "string" && MONEY.test(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalid(message: string): PaperTerminalDisplay {
  return { kind: "invalid", message };
}
