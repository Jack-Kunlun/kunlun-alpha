import type {
  InstrumentDailyBar as SharedInstrumentDailyBar,
  Instrument,
  KolClaim,
  KolEvidence,
  MarketEvent,
  SeatTrade,
  Sector,
  SectorMembership,
} from "@kunlun/shared-types";

export type InstrumentDailyBar = SharedInstrumentDailyBar;

export interface PitRecord<T> {
  data: T;
  eventTime: string;
  availableTime: string;
  processingTime: string;
  sourceVersions: string[];
  evidenceIds: string[];
}

export interface SectorContext {
  sector: Sector;
  membership: SectorMembership;
}

export interface PostgresInstrumentContext {
  identity: PitRecord<Instrument> | null;
  sectors: PitRecord<SectorContext>[];
  events: PitRecord<MarketEvent>[];
  seats: PitRecord<SeatTrade>[];
  claims: PitRecord<KolClaim>[];
  evidence: PitRecord<KolEvidence>[];
}

export interface InstrumentMarketBar {
  date: string;
  eventTime: string;
  open: string;
  high: string;
  low: string;
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

export interface InstrumentEmotionSnapshot {
  eventTime: string;
  score: string;
  confidenceBps: number;
  sampleSize: number;
  algorithmVersion: string;
  sourceVersions: string[];
  evidenceIds: string[];
  availableTime: string;
  processingTime: string;
}

export interface InstrumentFeatureValue {
  featureName: string;
  featureVersion: string;
  featureFingerprint: string;
  algorithmVersion: string;
  valueType: string;
  value: unknown;
  eventTime: string;
  availableTime: string;
  processingTime: string;
  lineageChecksum: string;
  sourceKind: string;
  sourceSnapshotVersion: string;
  revisionId: string;
}

export interface InstrumentMarketReadModel {
  load(instrumentId: string, asOf: string): Promise<InstrumentMarketBar | null>;
}

export interface InstrumentBarsReadModel {
  load(instrumentId: string, asOf: string, limit: number): Promise<InstrumentDailyBar[]>;
}

export interface InstrumentEmotionReadModel {
  load(asOf: string): Promise<InstrumentEmotionSnapshot | null>;
}

export interface InstrumentFeatureReadModel {
  load(instrumentId: string, asOf: string): Promise<InstrumentFeatureValue[]>;
}

export interface PostgresInstrumentContextReadModel {
  load(instrumentId: string, asOf: string): Promise<PostgresInstrumentContext>;
}
