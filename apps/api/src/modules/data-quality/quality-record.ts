/**
 * Data quality record.
 *
 * A quality event is located by date, source and instrument, and links back
 * to the raw evidence (an immutable raw object id). The panel must surface
 * every record's detail, never only aggregate totals.
 */

export interface DataQualityRecord {
  id: string;
  kind: string;
  date: string;
  source: string;
  unifiedCode: string | null;
  detail: string;
  evidenceLink: string;
}
