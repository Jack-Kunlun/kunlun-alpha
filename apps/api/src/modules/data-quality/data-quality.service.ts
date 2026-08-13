import { Inject, Injectable, Optional } from "@nestjs/common";
import type { DataQualityRecord } from "./quality-record";

export interface QualityQuery {
  date?: string;
  source?: string;
  unifiedCode?: string;
}

export const DATA_QUALITY_RECORDS = Symbol("DATA_QUALITY_RECORDS");

@Injectable()
export class DataQualityService {
  constructor(
    @Optional() @Inject(DATA_QUALITY_RECORDS) private readonly records: DataQualityRecord[] = [],
  ) {}

  query(filter: QualityQuery = {}): DataQualityRecord[] {
    return this.records.filter((record) => {
      if (filter.date && record.date !== filter.date) return false;
      if (filter.source && record.source !== filter.source) return false;
      if (filter.unifiedCode && record.unifiedCode !== filter.unifiedCode) return false;
      return true;
    });
  }
}
