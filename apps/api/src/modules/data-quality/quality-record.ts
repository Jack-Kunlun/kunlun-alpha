/**
 * Data quality record read model.
 *
 * A quality event is located by trading date, source and instrument, and its
 * evidence is addressed only through a safe internal id — never a raw object
 * filesystem path, DSN, token, credential, or raw exception text. The `detail`
 * field is a controlled, human-readable reason derived from the event kind,
 * never the raw persisted digest or provider text.
 */

export interface DataQualityRecord {
  /** Immutable quality event id (safe internal identifier). */
  id: string;
  /** Quality event kind, e.g. SOURCE_CONFLICT. */
  kind: string;
  /** Suffix-form instrument code, e.g. 600519.SH, or null when not applicable. */
  unifiedCode: string | null;
  /** Trading date in Asia/Shanghai (YYYY-MM-DD). */
  date: string;
  /** Provenance source, or null when no evidence links exist. */
  source: string | null;
  /** Controlled human-readable reason derived from the event kind. */
  detail: string;
  /** First-write audit timestamp (UTC ISO 8601). */
  createdAt: string;
  /** Transport availability timestamp, or null when unavailable (freshness). */
  availableAt: string | null;
  /** Contract schema version of the producing pipeline. */
  schemaVersion: string;
}

/**
 * A safe evidence record. It intentionally never exposes raw object ids,
 * capture ids, checksums, payload digests, or storage paths.
 */
export interface EvidenceRecord {
  /** Safe internal evidence id. */
  id: string;
  source: string;
  schemaVersion: string;
  availableAt: string | null;
}

const QUALITY_REASON_BY_KIND: Record<string, string> = {
  SOURCE_CONFLICT: "多来源观测不一致，未选择权威值",
};

/**
 * Map a quality event kind to a controlled, human-readable reason. Unknown
 * kinds fall back to a generic message instead of leaking raw detail.
 */
export function reasonForKind(kind: string): string {
  return QUALITY_REASON_BY_KIND[kind] ?? "数据质量问题";
}
