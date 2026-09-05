import type {
  MarketQualityEvidenceDetail,
  MarketQualityEvidencePage,
  MarketQualityEvidenceRecord,
} from "@kunlun/shared-types";
import {
  matchesMarketQualityEvidenceDateWindow,
  type MarketQualityEvidenceQuery,
} from "./market-quality-evidence.query";
import {
  MarketQualityEvidenceReadError,
  type MarketQualityEvidenceSnapshotReader,
} from "./market-quality-evidence.reader";

export class MarketQualityEvidenceNotFoundError extends Error {
  constructor() {
    super("market quality evidence record was not found");
    this.name = "MarketQualityEvidenceNotFoundError";
  }
}

export interface MarketQualityEvidenceReadModel {
  list(query: MarketQualityEvidenceQuery): Promise<MarketQualityEvidencePage>;
  detail(opaqueId: string, snapshotId: string): Promise<MarketQualityEvidenceDetail>;
}

function matches(record: MarketQualityEvidenceRecord, query: MarketQualityEvidenceQuery): boolean {
  return (
    (query.source === undefined || record.source === query.source) &&
    (query.unifiedCode === undefined || record.unifiedCode === query.unifiedCode) &&
    (query.status === undefined || record.status === query.status) &&
    matchesMarketQualityEvidenceDateWindow(record, query)
  );
}

/** Secure, deterministic query projection over one immutable evidence snapshot. */
export class FileMarketQualityEvidenceReadModel implements MarketQualityEvidenceReadModel {
  constructor(private readonly reader: MarketQualityEvidenceSnapshotReader) {}

  async list(query: MarketQualityEvidenceQuery): Promise<MarketQualityEvidencePage> {
    const loaded = await this.load(query.snapshotId);
    const matching = loaded.snapshot.records.filter((record) => matches(record, query));
    const records = matching.slice(query.offset, query.offset + query.limit);
    return {
      schemaVersion: "market-quality-evidence-v1",
      snapshotId: loaded.snapshotId,
      publishedAt: loaded.snapshot.publishedAt,
      snapshotRecordCount: loaded.snapshot.records.length,
      matchingRecordCount: matching.length,
      offset: query.offset,
      limit: query.limit,
      hasMore: query.offset + records.length < matching.length,
      records,
    };
  }

  async detail(opaqueId: string, snapshotId: string): Promise<MarketQualityEvidenceDetail> {
    const loaded = await this.load(snapshotId);
    const record = loaded.snapshot.records.find((candidate) => candidate.evidenceId === opaqueId);
    if (record === undefined) throw new MarketQualityEvidenceNotFoundError();
    return {
      schemaVersion: "market-quality-evidence-v1",
      snapshotId: loaded.snapshotId,
      publishedAt: loaded.snapshot.publishedAt,
      record,
    };
  }

  private async load(snapshotId: string | undefined) {
    try {
      return snapshotId === undefined
        ? await this.reader.readCurrent()
        : await this.reader.readSnapshot(snapshotId);
    } catch (error) {
      if (error instanceof MarketQualityEvidenceReadError) throw error;
      throw new MarketQualityEvidenceReadError();
    }
  }
}

export class UnavailableMarketQualityEvidenceReadModel implements MarketQualityEvidenceReadModel {
  async list(_query: MarketQualityEvidenceQuery): Promise<MarketQualityEvidencePage> {
    throw new MarketQualityEvidenceReadError();
  }

  async detail(_opaqueId: string, _snapshotId: string): Promise<MarketQualityEvidenceDetail> {
    throw new MarketQualityEvidenceReadError();
  }
}
