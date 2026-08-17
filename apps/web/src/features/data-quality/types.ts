/**
 * Data-quality types for the Web terminal.
 *
 * Mirrors the API response shape; evidence is addressed only through a safe
 * internal endpoint — the client never sees a raw object path or credential.
 */

export interface DataQualityRecord {
  id: string;
  kind: string;
  unifiedCode: string | null;
  date: string;
  source: string | null;
  detail: string;
  createdAt: string;
  availableAt: string | null;
  schemaVersion: string;
}
