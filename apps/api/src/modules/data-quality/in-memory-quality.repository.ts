/**
 * In-memory quality repository for unit tests.
 */

import type { DataQualityRecord, EvidenceRecord } from "./quality-record";
import type { QualityQuery, QualityRepository } from "./quality-repository";

export class InMemoryQualityRepository implements QualityRepository {
  constructor(
    private readonly records: DataQualityRecord[] = [],
    private readonly evidence: EvidenceRecord[] = [],
  ) {}

  async query(filters: QualityQuery): Promise<DataQualityRecord[]> {
    return this.records.filter((record) => {
      if (filters.date !== undefined && record.date !== filters.date) return false;
      if (filters.dateFrom !== undefined && record.date < filters.dateFrom) return false;
      if (filters.dateTo !== undefined && record.date > filters.dateTo) return false;
      if (filters.source !== undefined && record.source !== filters.source) return false;
      if (filters.unifiedCode !== undefined && record.unifiedCode !== filters.unifiedCode) return false;
      if (filters.kind !== undefined && record.kind !== filters.kind) return false;
      return true;
    });
  }

  async getEvidence(eventId: string): Promise<EvidenceRecord | null> {
    return this.evidence.find((item) => item.id === eventId) ?? null;
  }
}
