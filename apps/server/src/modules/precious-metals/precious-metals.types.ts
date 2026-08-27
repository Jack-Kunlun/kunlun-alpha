import type { PreciousMetalFund } from "@kunlun/shared-types";

export interface PreciousMetalsFundRecord {
  data: PreciousMetalFund;
  eventTime: string;
  availableTime: string;
  processingTime: string;
  sourceVersion: string;
  evidenceId: string;
}

export interface PreciousMetalsReferenceRecord {
  kind: "NAV" | "INAV";
  instrumentId: string;
  referenceDate: string;
  value: string;
  eventTime: string | null;
  availableTime: string;
  processingTime: string;
  source: string;
  sourceVersion: string;
  evidenceId: string;
}

export interface PreciousMetalsEventRecord {
  eventId: string;
  instrumentIds: string[];
  eventType: string;
  headline: string;
  summary: string;
  publishTime: string;
  availableTime: string;
  processingTime: string;
  confidenceBps: number;
  modelVersion: string;
  sourceVersions: string[];
  evidenceIds: string[];
}

export interface PreciousMetalsPostgresContext {
  funds: PreciousMetalsFundRecord[];
  references: PreciousMetalsReferenceRecord[];
  events: PreciousMetalsEventRecord[];
}

export interface PreciousMetalsMarketRecord {
  instrumentId: string;
  date: string;
  eventTime: string;
  close: string;
  volume: string;
  amount: string;
  suspended: boolean;
  dataVersion: string;
  source: string;
  sourceVersion: string;
  evidenceId: string;
  availableTime: string;
  processingTime: string;
}

export interface PreciousMetalsFeatureRecord {
  instrumentId: string;
  featureName: string;
  featureVersion: string;
  algorithmVersion: string;
  valueType: "BOOLEAN" | "INTEGER" | "DECIMAL" | "STRING" | "CATEGORY";
  value: string;
  eventTime: string;
  availableTime: string;
  processingTime: string;
  evidenceId: string;
}

export interface PreciousMetalsPostgresReadModel {
  load(asOf: string): Promise<PreciousMetalsPostgresContext>;
}

export interface PreciousMetalsMarketReadModel {
  load(instrumentIds: readonly string[], asOf: string): Promise<PreciousMetalsMarketRecord[]>;
}

export interface PreciousMetalsFeatureReadModel {
  load(instrumentIds: readonly string[], asOf: string): Promise<PreciousMetalsFeatureRecord[]>;
}
