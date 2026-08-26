import type {
  InstrumentIntelligenceDetail,
  KolEvidence,
  MarketEvent,
} from "@kunlun/shared-types";
import { ForbiddenException, Inject, Injectable } from "@nestjs/common";
import {
  parseInstrumentId,
  parseInstrumentIntelligenceQuery,
  type InstrumentIntelligenceClock,
} from "./instrument-intelligence.query";
import {
  INSTRUMENT_INTELLIGENCE_AUTHORIZER,
  INSTRUMENT_INTELLIGENCE_CLOCK,
  INSTRUMENT_INTELLIGENCE_EMOTION,
  INSTRUMENT_INTELLIGENCE_FEATURES,
  INSTRUMENT_INTELLIGENCE_MARKET,
  INSTRUMENT_INTELLIGENCE_POSTGRES,
} from "./instrument-intelligence.tokens";
import type {
  InstrumentEmotionReadModel,
  InstrumentFeatureReadModel,
  InstrumentFeatureValue,
  InstrumentMarketBar,
  InstrumentMarketReadModel,
  PitRecord,
  PostgresInstrumentContext,
  PostgresInstrumentContextReadModel,
} from "./read-model.types";

export interface InstrumentIntelligenceAuthorizer {
  canRead(): Promise<boolean>;
}

export class AllowAllInstrumentIntelligenceAuthorizer
  implements InstrumentIntelligenceAuthorizer
{
  async canRead(): Promise<true> {
    return true;
  }
}

type SectionStatus = "AVAILABLE" | "EMPTY" | "UNAVAILABLE";

interface SectionEnvelope<T> {
  status: SectionStatus;
  requestedAsOf: string;
  effectiveAsOf: string;
  dataCutoffTime: string | null;
  availableTime: string | null;
  processingTime: string | null;
  freshnessSeconds: number | null;
  unavailableReason: string | null;
  sourceVersions: string[];
  evidenceIds: string[];
  data: T;
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values)].sort();
}

function latest(values: readonly string[]): string | null {
  return values.length === 0
    ? null
    : [...values].sort((left, right) => Date.parse(right) - Date.parse(left))[0] ?? null;
}

function visible(records: readonly PitRecord<unknown>[], asOf: string): void {
  const cutoff = Date.parse(asOf);
  if (
    records.some(
      (record) =>
        Date.parse(record.availableTime) > cutoff || Date.parse(record.processingTime) > cutoff,
    )
  ) {
    throw new Error("point-in-time repository returned a future-visible record");
  }
}

function section<T>(
  data: T,
  records: readonly PitRecord<unknown>[],
  requestedAsOf: string,
  effectiveAsOf: string,
  empty: boolean,
): SectionEnvelope<T> {
  visible(records, effectiveAsOf);
  const availableTime = latest(records.map((record) => record.availableTime));
  const processingTime = latest(records.map((record) => record.processingTime));
  const dataCutoffTime = availableTime;
  return {
    status: empty ? "EMPTY" : "AVAILABLE",
    requestedAsOf,
    effectiveAsOf,
    dataCutoffTime,
    availableTime,
    processingTime,
    freshnessSeconds:
      dataCutoffTime === null
        ? null
        : Math.max(
            0,
            Math.floor((Date.parse(effectiveAsOf) - Date.parse(dataCutoffTime)) / 1000),
          ),
    unavailableReason: null,
    sourceVersions: unique(records.flatMap((record) => record.sourceVersions)),
    evidenceIds: unique(records.flatMap((record) => record.evidenceIds)),
    data,
  };
}

function unavailable<T>(
  data: T,
  requestedAsOf: string,
  effectiveAsOf: string,
  reason: string,
): SectionEnvelope<T> {
  return {
    status: "UNAVAILABLE",
    requestedAsOf,
    effectiveAsOf,
    dataCutoffTime: null,
    availableTime: null,
    processingTime: null,
    freshnessSeconds: null,
    unavailableReason: reason,
    sourceVersions: [],
    evidenceIds: [],
    data,
  };
}

function marketRecord(value: InstrumentMarketBar): PitRecord<InstrumentMarketBar> {
  return {
    data: value,
    eventTime: value.eventTime,
    availableTime: value.availableTime,
    processingTime: value.processingTime,
    sourceVersions: [value.source + "@" + value.sourceVersion, value.dataVersion],
    evidenceIds: [value.evidenceId],
  };
}

function featureRecord(value: InstrumentFeatureValue): PitRecord<InstrumentFeatureValue> {
  return {
    data: value,
    eventTime: value.eventTime,
    availableTime: value.availableTime,
    processingTime: value.processingTime,
    sourceVersions: [
      value.sourceKind + "@" + value.sourceSnapshotVersion,
      value.algorithmVersion,
      value.featureVersion,
    ],
    evidenceIds: [value.lineageChecksum, value.revisionId],
  };
}

function safeLocator(value: KolEvidence): string | null {
  if (value.locatorType !== "URL") return null;
  try {
    const url = new URL(value.locator);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function evidenceLinks(
  context: PostgresInstrumentContext,
): InstrumentIntelligenceDetail["evidence"] {
  const links = new Map<string, InstrumentIntelligenceDetail["evidence"][number]>();
  for (const record of context.evidence) {
    const locator = safeLocator(record.data);
    links.set(record.data.evidenceId, {
      evidenceId: record.data.evidenceId,
      source: record.data.source,
      sourceVersion: record.data.sourceVersion,
      availableTime: record.availableTime,
      excerpt: record.data.excerpt,
      locator,
      access: locator === null ? "REFERENCE_ONLY" : "DIRECT_URL",
    });
  }
  for (const event of context.events.map((record) => record.data)) {
    for (const evidence of event.evidence) {
      if (!links.has(evidence.evidenceId)) {
        links.set(evidence.evidenceId, {
          evidenceId: evidence.evidenceId,
          source: evidence.sourceId,
          sourceVersion: evidence.sourceVersion,
          availableTime: evidence.availableTime,
          excerpt: evidence.excerpt,
          locator: null,
          access: "REFERENCE_ONLY",
        });
      }
    }
  }
  const referenced = unique([
    ...(context.identity?.evidenceIds ?? []),
    ...context.sectors.flatMap((record) => record.evidenceIds),
    ...context.events.flatMap((record) => record.evidenceIds),
    ...context.seats.flatMap((record) => record.evidenceIds),
    ...context.claims.flatMap((record) => record.evidenceIds),
  ]);
  for (const evidenceId of referenced) {
    if (!links.has(evidenceId)) {
      links.set(evidenceId, {
        evidenceId,
        source: null,
        sourceVersion: null,
        availableTime: null,
        excerpt: null,
        locator: null,
        access: "REFERENCE_ONLY",
      });
    }
  }
  return [...links.values()].sort((left, right) =>
    left.evidenceId.localeCompare(right.evidenceId),
  );
}

function eventItem(event: MarketEvent) {
  return {
    eventId: event.eventId,
    eventType: event.eventType,
    headline: event.headline,
    summary: event.summary,
    occurTime: event.occurTime,
    publishTime: event.publishTime,
    availableTime: event.availableTime,
    confidenceBps: event.confidenceBps,
    modelVersion: event.modelProvenance.modelVersion,
    evidenceIds: event.evidence.map((item) => item.evidenceId),
  };
}

@Injectable()
export class InstrumentIntelligenceService {
  constructor(
    @Inject(INSTRUMENT_INTELLIGENCE_POSTGRES)
    private readonly postgres: PostgresInstrumentContextReadModel,
    @Inject(INSTRUMENT_INTELLIGENCE_MARKET)
    private readonly market: InstrumentMarketReadModel,
    @Inject(INSTRUMENT_INTELLIGENCE_EMOTION)
    private readonly emotion: InstrumentEmotionReadModel,
    @Inject(INSTRUMENT_INTELLIGENCE_FEATURES)
    private readonly features: InstrumentFeatureReadModel,
    @Inject(INSTRUMENT_INTELLIGENCE_AUTHORIZER)
    private readonly authorizer: InstrumentIntelligenceAuthorizer,
    @Inject(INSTRUMENT_INTELLIGENCE_CLOCK)
    private readonly clock: InstrumentIntelligenceClock,
  ) {}

  async detail(
    rawInstrumentId: string,
    rawQuery: Record<string, unknown>,
  ): Promise<InstrumentIntelligenceDetail> {
    if (!(await this.authorizer.canRead())) {
      throw new ForbiddenException("无权访问个股 Intelligence 详情");
    }
    const instrumentId = parseInstrumentId(rawInstrumentId);
    const query = parseInstrumentIntelligenceQuery(rawQuery, this.clock);
    const asOf = query.effectiveAsOf;
    const [postgresResult, marketResult, emotionResult, featureResult] =
      await Promise.allSettled([
        this.postgres.load(instrumentId, asOf),
        this.market.load(instrumentId, asOf),
        this.emotion.load(asOf),
        this.features.load(instrumentId, asOf),
      ]);

    const postgres =
      postgresResult.status === "fulfilled" ? postgresResult.value : null;
    const identity =
      postgres === null
        ? unavailable(null, query.requestedAsOf, asOf, "POSTGRES_QUERY_FAILED")
        : section(
            postgres.identity?.data ?? null,
            postgres.identity ? [postgres.identity] : [],
            query.requestedAsOf,
            asOf,
            postgres.identity === null,
          );
    const sector =
      postgres === null
        ? unavailable([], query.requestedAsOf, asOf, "POSTGRES_QUERY_FAILED")
        : section(
            postgres.sectors.map((record) => ({
              sectorId: record.data.sector.sectorId,
              name: record.data.sector.name,
              kind: record.data.sector.kind,
              validFrom: record.data.membership.validFrom,
              validTo: record.data.membership.validTo ?? null,
              source: record.data.membership.source,
              sourceVersion: record.data.membership.sourceVersion,
              availableTime: record.data.membership.availableTime,
              evidenceId: record.data.membership.evidenceId,
            })),
            postgres.sectors,
            query.requestedAsOf,
            asOf,
            postgres.sectors.length === 0,
          );
    const events =
      postgres === null
        ? unavailable([], query.requestedAsOf, asOf, "POSTGRES_QUERY_FAILED")
        : section(
            postgres.events.map((record) => eventItem(record.data)),
            postgres.events,
            query.requestedAsOf,
            asOf,
            postgres.events.length === 0,
          );
    const seats =
      postgres === null
        ? unavailable([], query.requestedAsOf, asOf, "POSTGRES_QUERY_FAILED")
        : section(
            postgres.seats.map((record) => ({
              tradeId: record.data.tradeId,
              revisionId: record.data.revisionId,
              seatId: record.data.seatId,
              rawSeatName: record.data.rawSeatName,
              tradeDate: record.data.tradeDate,
              currency: record.data.currency,
              buyAmount: record.data.buyAmount,
              sellAmount: record.data.sellAmount,
              netAmount: record.data.netAmount,
              availableTime: record.data.availableTime,
              evidenceId: record.data.evidenceId,
              dataMeaning: "PUBLIC_DRAGON_TIGER_FACT_NOT_BROKER_ORDER" as const,
            })),
            postgres.seats,
            query.requestedAsOf,
            asOf,
            postgres.seats.length === 0,
          );
    const kolClaims =
      postgres === null
        ? unavailable([], query.requestedAsOf, asOf, "POSTGRES_QUERY_FAILED")
        : section(
            postgres.claims.map((record) => ({
              claimId: record.data.claimId,
              revisionId: record.data.revisionId,
              kolId: record.data.kolId,
              statement: record.data.statement,
              direction: record.data.direction,
              reviewStatus: record.data.reviewStatus,
              confidenceBps: record.data.confidenceBps,
              publishTime: record.data.publishTime,
              availableTime: record.data.availableTime,
              evidenceIds: record.data.evidence.map((item) => item.evidenceId),
              claimMeaning: "PUBLIC_WORDING_CLAIM_NOT_BROKER_TRADE" as const,
            })),
            postgres.claims,
            query.requestedAsOf,
            asOf,
            postgres.claims.length === 0,
          );

    const market =
      marketResult.status === "rejected"
        ? unavailable(null, query.requestedAsOf, asOf, "CLICKHOUSE_MARKET_QUERY_FAILED")
        : section(
            marketResult.value,
            marketResult.value === null ? [] : [marketRecord(marketResult.value)],
            query.requestedAsOf,
            asOf,
            marketResult.value === null,
          );
    const emotion =
      emotionResult.status === "rejected"
        ? unavailable(null, query.requestedAsOf, asOf, "CLICKHOUSE_EMOTION_QUERY_FAILED")
        : section(
            emotionResult.value,
            emotionResult.value === null
              ? []
              : [
                  {
                    data: emotionResult.value,
                    eventTime: emotionResult.value.eventTime,
                    availableTime: emotionResult.value.availableTime,
                    processingTime: emotionResult.value.processingTime,
                    sourceVersions: emotionResult.value.sourceVersions,
                    evidenceIds: emotionResult.value.evidenceIds,
                  },
                ],
            query.requestedAsOf,
            asOf,
            emotionResult.value === null,
          );
    const features =
      featureResult.status === "rejected"
        ? unavailable([], query.requestedAsOf, asOf, "CLICKHOUSE_FEATURE_QUERY_FAILED")
        : section(
            featureResult.value,
            featureResult.value.map(featureRecord),
            query.requestedAsOf,
            asOf,
            featureResult.value.length === 0,
          );

    const response = {
      schemaVersion: "instrument-intelligence-detail-v1",
      dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
      instrumentId,
      mode: query.mode,
      requestedAsOf: query.requestedAsOf,
      effectiveAsOf: asOf,
      generatedAt: query.generatedAt,
      snapshotBoundary: {
        consistency: "BEST_EFFORT_CROSS_STORE",
        postgresIsolation: "REPEATABLE_READ",
        effectiveAsOf: asOf,
        stores: ["POSTGRESQL", "CLICKHOUSE"],
      },
      sections: {
        identity,
        market,
        emotion,
        sector,
        events,
        seats,
        kolClaims,
        features,
      },
      evidence: postgres === null ? [] : evidenceLinks(postgres),
    } as const;
    return response as InstrumentIntelligenceDetail;
  }
}
