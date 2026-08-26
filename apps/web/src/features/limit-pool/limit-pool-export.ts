import type { LimitPoolTerminalEntry, LimitPoolTerminalSnapshot } from "@kunlun/shared-types";

const SNAPSHOT_HEADERS = [
  "请求点时",
  "数据截止时间",
  "快照可得时间",
  "交易日",
  "前一交易日",
  "完整性",
  "缺失原因",
  "新鲜度",
  "数据龄(秒)",
  "快照来源版本",
  "快照证据ID",
  "数据语义",
];

const ENTRY_HEADERS = [
  "证券代码",
  "证券名称",
  "方向",
  "状态",
  "连板天数",
  "开板次数",
  "价格(CNY)",
  "昨收(CNY)",
  "首次封板",
  "最近封板",
  "事件时间",
  "可得时间",
  "修订",
  "来源版本",
  "证据ID",
  "算法版本",
  "梯队算法版本",
  "涨跌停规则版本",
  "物化器版本",
];

function cell(value: string | number | null): string {
  const text = String(value ?? "");
  const safe = typeof value === "string" && /^[\t\r\n ]*[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}

function snapshotCells(snapshot: LimitPoolTerminalSnapshot): (string | number | null)[] {
  return [
    snapshot.requestedAsOf,
    snapshot.dataCutoffTime,
    snapshot.availableTime,
    snapshot.tradingDate,
    snapshot.previousTradingDate,
    snapshot.completeness,
    snapshot.missingReasons.join("|"),
    snapshot.freshness.status,
    snapshot.freshness.ageSeconds,
    snapshot.sourceVersions.join("|"),
    snapshot.evidenceIds.join("|"),
    snapshot.dataMeaning,
  ];
}

export function buildLimitPoolCsv(
  snapshot: LimitPoolTerminalSnapshot,
  entries: readonly LimitPoolTerminalEntry[] = snapshot.entries,
): string {
  const metadata = snapshotCells(snapshot);
  const rows = entries.map((entry) =>
    [
      ...metadata,
      entry.instrumentId,
      entry.name,
      entry.side,
      entry.state,
      entry.streakDays,
      entry.openCount,
      entry.priceCny,
      entry.previousCloseCny,
      entry.firstSealTime,
      entry.lastSealTime,
      entry.eventTime,
      entry.availableTime,
      entry.revision,
      entry.sourceVersion,
      entry.evidenceId,
      entry.algorithmVersion,
      entry.ladderAlgorithmVersion,
      entry.limitRuleVersion,
      entry.materializerVersion,
    ]
      .map(cell)
      .join(","),
  );
  return `\uFEFF${[...SNAPSHOT_HEADERS, ...ENTRY_HEADERS].map(cell).join(",")}\r\n${rows.join("\r\n")}\r\n`;
}

export function downloadLimitPoolCsv(
  snapshot: LimitPoolTerminalSnapshot,
  entries: readonly LimitPoolTerminalEntry[],
): void {
  const blob = new Blob([buildLimitPoolCsv(snapshot, entries)], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `limit-pool-${snapshot.tradingDate ?? "unknown"}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}
