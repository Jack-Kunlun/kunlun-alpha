/**
 * Persisted quality-event repository port.
 *
 * The service depends on this port — never on an injected constant array.
 * A PostgreSQL adapter reads the data-worker's `fund_quality_events` tables;
 * an in-memory adapter backs unit tests. A repository failure must propagate
 * (throw), never be swallowed into an empty success.
 */

import type { DataQualityRecord, EvidenceRecord } from "./quality-record";

export interface QualityQuery {
  /** Single trading date (YYYY-MM-DD). */
  date?: string;
  /** Inclusive start of a trading-date range (YYYY-MM-DD). */
  dateFrom?: string;
  /** Inclusive end of a trading-date range (YYYY-MM-DD). */
  dateTo?: string;
  /** Provenance source. */
  source?: string;
  /** Suffix-form instrument code, e.g. 600519.SH. */
  unifiedCode?: string;
  /** Quality event kind, e.g. SOURCE_CONFLICT. */
  kind?: string;
}

export interface QualityRepository {
  /** Query persisted quality events with validated filters. */
  query(filters: QualityQuery): Promise<DataQualityRecord[]>;
  /** Fetch a single evidence record by its safe internal id. */
  getEvidence(eventId: string): Promise<EvidenceRecord | null>;
}
