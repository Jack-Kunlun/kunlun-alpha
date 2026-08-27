import type { PreciousMetalsTerminalSnapshot } from "@kunlun/shared-types";
import { ForbiddenException, Inject, Injectable } from "@nestjs/common";
import {
  parsePreciousMetalsQuery,
  type PreciousMetalsClock,
  type PreciousMetalsQuery,
} from "./precious-metals.query";
import {
  PRECIOUS_METALS_AUTHORIZER,
  PRECIOUS_METALS_CLOCK,
  PRECIOUS_METALS_FEATURES,
  PRECIOUS_METALS_MARKET,
  PRECIOUS_METALS_POSTGRES,
} from "./precious-metals.tokens";
import type {
  PreciousMetalsFeatureReadModel,
  PreciousMetalsFundRecord,
  PreciousMetalsMarketReadModel,
  PreciousMetalsPostgresContext,
  PreciousMetalsPostgresReadModel,
  PreciousMetalsReferenceRecord,
} from "./precious-metals.types";

const INAV_FRESH_SECONDS = 5 * 60;
const NAV_FRESH_SECONDS = 7 * 24 * 60 * 60;
const MARKET_FRESH_SECONDS = 3 * 24 * 60 * 60;
const RANKING_VERSION = "precious-metals-turnover-ranking-v1" as const;

type FundOutput = PreciousMetalsTerminalSnapshot["funds"][number];
type GapOutput = PreciousMetalsTerminalSnapshot["gaps"][number];

export interface PreciousMetalsAuthorizer {
  canRead(): Promise<boolean>;
}

export class AllowAllPreciousMetalsAuthorizer implements PreciousMetalsAuthorizer {
  async canRead(): Promise<true> {
    return true;
  }
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values)].sort();
}

function terminalReviewStatus(
  value: PreciousMetalsFundRecord["data"]["reviewStatus"],
): FundOutput["reviewStatus"] {
  if (value === "REVIEWED" || value === "NEEDS_REVIEW") {
    return value;
  }
  throw new Error("precious-metals terminal rejected an ineligible classification status");
}

function nonEmptyStrings(values: readonly string[]): [string, ...string[]] | null {
  const [first, ...rest] = values;
  return first === undefined ? null : [first, ...rest];
}

function ageSeconds(asOf: string, eventTime: string): number {
  const age = Math.floor((Date.parse(asOf) - Date.parse(eventTime)) / 1000);
  if (!Number.isFinite(age) || age < 0) {
    throw new Error("point-in-time source returned a future or invalid event time");
  }
  return age;
}

function assertVisible(
  values: readonly { availableTime: string; processingTime: string }[],
  asOf: string,
): void {
  const cutoff = Date.parse(asOf);
  if (
    values.some(
      (value) =>
        Date.parse(value.availableTime) > cutoff || Date.parse(value.processingTime) > cutoff,
    )
  ) {
    throw new Error("point-in-time repository returned a future-visible record");
  }
}

interface DecimalParts {
  coefficient: bigint;
  scale: bigint;
}

function decimalParts(value: string): DecimalParts {
  const match = /^(0|[1-9]\d*)(?:\.(\d+))?$/.exec(value);
  if (!match) throw new Error("invalid non-negative decimal wire value");
  const fraction = match[2] ?? "";
  return {
    coefficient: BigInt((match[1] ?? "0") + fraction),
    scale: 10n ** BigInt(fraction.length),
  };
}

function compareDecimal(left: string, right: string): number {
  const a = decimalParts(left);
  const b = decimalParts(right);
  const comparison = a.coefficient * b.scale - b.coefficient * a.scale;
  return comparison === 0n ? 0 : comparison > 0n ? 1 : -1;
}

function fixedSigned(value: bigint, scaleDigits: number): string {
  const negative = value < 0n;
  const absolute = negative ? -value : value;
  const scale = 10n ** BigInt(scaleDigits);
  const whole = absolute / scale;
  const fraction = (absolute % scale).toString().padStart(scaleDigits, "0");
  return `${negative ? "-" : ""}${whole}.${fraction}`;
}

function premiumDiscountBps(price: string, reference: string): string {
  const market = decimalParts(price);
  const ref = decimalParts(reference);
  if (ref.coefficient === 0n) throw new Error("NAV/iNAV reference must be positive");
  const numerator = market.coefficient * ref.scale - ref.coefficient * market.scale;
  const denominator = ref.coefficient * market.scale;
  const scaledNumerator = numerator * 1_000_000n;
  const absolute = scaledNumerator < 0n ? -scaledNumerator : scaledNumerator;
  let quotient = absolute / denominator;
  if ((absolute % denominator) * 2n >= denominator) quotient += 1n;
  return fixedSigned(scaledNumerator < 0n ? -quotient : quotient, 2);
}

function displayName(record: PreciousMetalsFundRecord): string {
  const commodity = {
    GOLD: "黄金",
    SILVER: "白银",
    OTHER: "其他贵金属",
  }[record.data.underlyingCommodity];
  return commodity + " " + record.data.assetType;
}

function referenceFor(
  instrumentId: string,
  references: readonly PreciousMetalsReferenceRecord[],
  asOf: string,
): {
  nav: PreciousMetalsReferenceRecord | null;
  inav: PreciousMetalsReferenceRecord | null;
  selected: PreciousMetalsReferenceRecord | null;
  staleAfterSeconds: number | null;
  freshness: "FRESH" | "STALE" | "MISSING";
} {
  const nav =
    references.find((record) => record.instrumentId === instrumentId && record.kind === "NAV") ??
    null;
  const inav =
    references.find((record) => record.instrumentId === instrumentId && record.kind === "INAV") ??
    null;
  const inavFresh =
    inav !== null &&
    inav.eventTime !== null &&
    ageSeconds(asOf, inav.eventTime) <= INAV_FRESH_SECONDS;
  const navFresh =
    nav !== null && nav.eventTime !== null && ageSeconds(asOf, nav.eventTime) <= NAV_FRESH_SECONDS;
  if (inavFresh) {
    return {
      nav,
      inav,
      selected: inav,
      staleAfterSeconds: INAV_FRESH_SECONDS,
      freshness: "FRESH",
    };
  }
  if (navFresh) {
    return {
      nav,
      inav,
      selected: nav,
      staleAfterSeconds: NAV_FRESH_SECONDS,
      freshness: "FRESH",
    };
  }
  return {
    nav,
    inav,
    selected: null,
    staleAfterSeconds: nav === null && inav === null ? null : NAV_FRESH_SECONDS,
    freshness: nav === null && inav === null ? "MISSING" : "STALE",
  };
}

function gap(
  scope: GapOutput["scope"],
  severity: GapOutput["severity"],
  code: GapOutput["code"],
  instrumentId: string | null,
  message: string,
): GapOutput {
  return { scope, severity, code, instrumentId, message };
}

function unavailableSnapshot(
  query: PreciousMetalsQuery,
  reason: string,
): PreciousMetalsTerminalSnapshot {
  return {
    schemaVersion: "precious-metals-terminal-v1",
    mode: query.mode,
    requestedAsOf: query.requestedAsOf,
    effectiveAsOf: query.effectiveAsOf,
    generatedAt: query.generatedAt,
    status: "UNAVAILABLE",
    executionCapability: "REFERENCE_ONLY",
    valuationPolicy: "NAV_INAV_NON_EXECUTABLE",
    rankingAlgorithmVersion: RANKING_VERSION,
    rankingMetric: "LATEST_EXCHANGE_TURNOVER_CNY",
    sampleSize: 0,
    gaps: [gap("METADATA", "ERROR", "SOURCE_UNAVAILABLE", null, reason)],
    sourceVersions: [],
    evidenceIds: [],
    funds: [],
    events: [],
  };
}

@Injectable()
export class PreciousMetalsService {
  constructor(
    @Inject(PRECIOUS_METALS_POSTGRES)
    private readonly postgres: PreciousMetalsPostgresReadModel,
    @Inject(PRECIOUS_METALS_MARKET)
    private readonly market: PreciousMetalsMarketReadModel,
    @Inject(PRECIOUS_METALS_FEATURES)
    private readonly features: PreciousMetalsFeatureReadModel,
    @Inject(PRECIOUS_METALS_AUTHORIZER)
    private readonly authorizer: PreciousMetalsAuthorizer,
    @Inject(PRECIOUS_METALS_CLOCK)
    private readonly clock: PreciousMetalsClock,
  ) {}

  async terminal(rawQuery: Record<string, unknown>): Promise<PreciousMetalsTerminalSnapshot> {
    if (!(await this.authorizer.canRead())) {
      throw new ForbiddenException("无权访问贵金属基金终端");
    }
    const query = parsePreciousMetalsQuery(rawQuery, this.clock);
    let context: PreciousMetalsPostgresContext;
    try {
      context = await this.postgres.load(query.effectiveAsOf);
    } catch {
      return unavailableSnapshot(query, "POSTGRES_QUERY_FAILED");
    }
    assertVisible(
      [...context.funds, ...context.references, ...context.events],
      query.effectiveAsOf,
    );
    if (context.funds.length === 0) {
      return {
        ...unavailableSnapshot(query, "NO_VISIBLE_PRECIOUS_METALS_METADATA"),
        status: "EMPTY",
        gaps: [
          gap("METADATA", "INFO", "NO_VISIBLE_DATA", null, "该点时没有可见的场内贵金属基金分类"),
        ],
      };
    }

    const instrumentIds = context.funds.map((record) => record.data.unifiedCode);
    const [marketResult, featureResult] = await Promise.allSettled([
      this.market.load(instrumentIds, query.effectiveAsOf),
      this.features.load(instrumentIds, query.effectiveAsOf),
    ]);
    const marketRecords = marketResult.status === "fulfilled" ? marketResult.value : [];
    const featureRecords = featureResult.status === "fulfilled" ? featureResult.value : [];
    assertVisible([...marketRecords, ...featureRecords], query.effectiveAsOf);

    const gaps: GapOutput[] = [];
    if (marketResult.status === "rejected") {
      gaps.push(
        gap("MARKET", "WARNING", "SOURCE_UNAVAILABLE", null, "CLICKHOUSE_MARKET_QUERY_FAILED"),
      );
    }
    if (featureResult.status === "rejected") {
      gaps.push(
        gap("FEATURES", "WARNING", "SOURCE_UNAVAILABLE", null, "CLICKHOUSE_FEATURE_QUERY_FAILED"),
      );
    }

    const funds = context.funds.map((record): FundOutput => {
      const instrumentId = record.data.unifiedCode;
      const marketRecord = marketRecords.find((item) => item.instrumentId === instrumentId) ?? null;
      const selectedReference = referenceFor(instrumentId, context.references, query.effectiveAsOf);
      const fundFeatures = featureRecords
        .filter((item) => item.instrumentId === instrumentId)
        .sort((left, right) => left.featureName.localeCompare(right.featureName));
      if (marketRecord === null && marketResult.status === "fulfilled") {
        gaps.push(
          gap("MARKET", "WARNING", "NO_VISIBLE_DATA", instrumentId, "该点时没有可见的交易所行情"),
        );
      }
      const marketFreshness =
        marketRecord === null ||
        ageSeconds(query.effectiveAsOf, marketRecord.eventTime) <= MARKET_FRESH_SECONDS
          ? "FRESH"
          : "STALE";
      if (marketRecord !== null && marketFreshness === "STALE") {
        gaps.push(gap("MARKET", "WARNING", "STALE_DATA", instrumentId, "交易所行情已超过三天"));
      }
      if (selectedReference.nav === null) {
        gaps.push(gap("NAV", "WARNING", "NO_VISIBLE_DATA", instrumentId, "缺少可见 NAV"));
      }
      if (selectedReference.inav === null) {
        gaps.push(gap("INAV", "INFO", "NO_VISIBLE_DATA", instrumentId, "未提供可见 iNAV"));
      }
      if (selectedReference.freshness === "STALE") {
        gaps.push(gap("NAV", "WARNING", "STALE_DATA", instrumentId, "NAV/iNAV 均超过可用时效"));
      }
      if (fundFeatures.length === 0 && featureResult.status === "fulfilled") {
        gaps.push(
          gap(
            "FEATURES",
            "INFO",
            "NO_VISIBLE_DATA",
            instrumentId,
            "该点时没有可见的贵金属基金特征",
          ),
        );
      }
      const reference = selectedReference.selected;
      const evidenceIds = unique(
        [selectedReference.nav?.evidenceId, selectedReference.inav?.evidenceId].filter(
          (value): value is string => value !== undefined,
        ),
      );
      return {
        unifiedCode: instrumentId,
        displayName: displayName(record),
        exchange: record.data.exchange,
        assetType: record.data.assetType,
        underlyingCommodity: record.data.underlyingCommodity,
        tradingCurrency: record.data.tradingCurrency,
        navCurrency: record.data.navCurrency,
        benchmarkOrTrackingIndex: record.data.benchmarkOrTrackingIndex,
        managementFeeRateBps: Math.round(record.data.managementFeeRate * 10_000),
        metadataConfidenceBps: Math.round(record.data.confidence * 10_000),
        reviewStatus: terminalReviewStatus(record.data.reviewStatus),
        metadataSource: record.data.source,
        metadataSourceVersion: record.sourceVersion,
        metadataAvailableTime: record.availableTime,
        metadataProcessingTime: record.processingTime,
        market:
          marketRecord === null
            ? null
            : {
                date: marketRecord.date,
                eventTime: marketRecord.eventTime,
                close: marketRecord.close,
                volume: marketRecord.volume,
                turnoverCny: marketRecord.amount,
                suspended: marketRecord.suspended,
                freshness: marketFreshness,
                source: marketRecord.source,
                sourceVersion: marketRecord.sourceVersion,
                dataVersion: marketRecord.dataVersion,
                availableTime: marketRecord.availableTime,
                processingTime: marketRecord.processingTime,
                evidenceId: marketRecord.evidenceId,
              },
        valuation: {
          navValue: selectedReference.nav?.value ?? null,
          inavValue: selectedReference.inav?.value ?? null,
          referenceKind: reference?.kind ?? null,
          referenceValue: reference?.value ?? null,
          referenceDate: reference?.referenceDate ?? null,
          premiumDiscountBps:
            marketRecord === null || reference === null
              ? null
              : premiumDiscountBps(marketRecord.close, reference.value),
          freshness: selectedReference.freshness,
          staleAfterSeconds: selectedReference.staleAfterSeconds,
          source: reference?.source ?? null,
          sourceVersion: reference?.sourceVersion ?? null,
          availableTime: reference?.availableTime ?? null,
          processingTime: reference?.processingTime ?? null,
          evidenceIds,
          referenceOnly: true,
        },
        features: fundFeatures.map((feature) => ({
          name: feature.featureName,
          value: feature.value,
          valueType: feature.valueType,
          featureVersion: feature.featureVersion,
          algorithmVersion: feature.algorithmVersion,
          eventTime: feature.eventTime,
          availableTime: feature.availableTime,
          processingTime: feature.processingTime,
          evidenceId: feature.evidenceId,
        })),
        ranking: null,
        alertContext: {
          instrumentId,
          supportedFields: ["LAST_PRICE", "FEATURE_VALUE"],
          premiumFeatureName: "precious_metals_fund.premium_discount_bps",
        },
      };
    });

    const ranked = funds
      .filter((fund) => fund.market !== null)
      .sort((left, right) => {
        const amount = compareDecimal(
          right.market?.turnoverCny ?? "0",
          left.market?.turnoverCny ?? "0",
        );
        return amount === 0 ? left.unifiedCode.localeCompare(right.unifiedCode) : amount;
      });
    const rankingById = new Map(
      ranked.map((fund, index) => [
        fund.unifiedCode,
        {
          rank: index + 1,
          metric: "LATEST_EXCHANGE_TURNOVER_CNY" as const,
          metricValue: fund.market?.turnoverCny ?? "0",
          algorithmVersion: RANKING_VERSION,
          sampleSize: ranked.length,
          confidenceBps: Math.min(
            fund.metadataConfidenceBps,
            fund.market?.freshness === "FRESH" ? 10_000 : 5_000,
            fund.valuation.freshness === "FRESH" ? 10_000 : 5_000,
          ),
        },
      ]),
    );
    const rankedFunds = funds.map((fund) => ({
      ...fund,
      ranking: rankingById.get(fund.unifiedCode) ?? null,
    }));
    const sourceVersions = unique([
      ...context.funds.flatMap((record) => [record.data.source + "@" + record.sourceVersion]),
      ...context.references.map((record) => record.source + "@" + record.sourceVersion),
      ...context.events.flatMap((record) => record.sourceVersions),
      ...marketRecords.flatMap((record) => [record.source + "@" + record.sourceVersion]),
      ...featureRecords.flatMap((record) => [record.featureVersion, record.algorithmVersion]),
    ]);
    const evidenceIds = unique([
      ...context.funds.map((record) => record.evidenceId),
      ...context.references.map((record) => record.evidenceId),
      ...context.events.flatMap((record) => record.evidenceIds),
      ...marketRecords.map((record) => record.evidenceId),
      ...featureRecords.map((record) => record.evidenceId),
    ]);
    const status = gaps.some((item) => item.severity === "ERROR" || item.severity === "WARNING")
      ? "PARTIAL"
      : "AVAILABLE";
    return {
      schemaVersion: "precious-metals-terminal-v1",
      mode: query.mode,
      requestedAsOf: query.requestedAsOf,
      effectiveAsOf: query.effectiveAsOf,
      generatedAt: query.generatedAt,
      status,
      executionCapability: "REFERENCE_ONLY",
      valuationPolicy: "NAV_INAV_NON_EXECUTABLE",
      rankingAlgorithmVersion: RANKING_VERSION,
      rankingMetric: "LATEST_EXCHANGE_TURNOVER_CNY",
      sampleSize: rankedFunds.length,
      gaps,
      sourceVersions,
      evidenceIds,
      funds: rankedFunds,
      events: context.events.flatMap((event) => {
        const instrumentIds = nonEmptyStrings(event.instrumentIds);
        const eventEvidenceIds = nonEmptyStrings(event.evidenceIds);
        return instrumentIds === null || eventEvidenceIds === null
          ? []
          : [
              {
                eventId: event.eventId,
                instrumentIds,
                eventType: event.eventType,
                headline: event.headline,
                summary: event.summary,
                publishTime: event.publishTime,
                availableTime: event.availableTime,
                confidenceBps: event.confidenceBps,
                modelVersion: event.modelVersion,
                evidenceIds: eventEvidenceIds,
              },
            ];
      }),
    };
  }
}
