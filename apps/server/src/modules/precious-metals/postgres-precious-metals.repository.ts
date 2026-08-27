import type { PreciousMetalFund } from "@kunlun/shared-types";
import type { Pool, PoolClient, QueryResultRow } from "pg";
import { validateMarketEventPayload } from "../event-intelligence/event-intelligence-validation";
import type {
  PreciousMetalsEventRecord,
  PreciousMetalsFundRecord,
  PreciousMetalsPostgresContext,
  PreciousMetalsPostgresReadModel,
  PreciousMetalsReferenceRecord,
} from "./precious-metals.types";

interface MetadataRow extends QueryResultRow {
  payload: unknown;
  event_time: Date | string | null;
  available_time: Date | string;
  processing_time: Date | string;
  source_version: string;
  evidence_id: string;
}

interface ReferenceRow extends QueryResultRow {
  kind: "NAV" | "INAV";
  unified_code: string;
  reference_date: Date | string;
  value: string;
  event_time: Date | string | null;
  available_time: Date | string;
  processing_time: Date | string;
  source: string;
  source_version: string;
  evidence_id: string;
}

interface EventRow extends QueryResultRow {
  payload: unknown;
}

export const PRECIOUS_METALS_METADATA_PIT_SQL = [
  "WITH visible AS (",
  "  SELECT m.payload, e.event_time, e.available_time, e.processing_time,",
  "         COALESCE(e.source_revision, e.schema_version || '+' || e.normalizer_version) AS source_version,",
  "         e.record_id AS evidence_id,",
  "         ROW_NUMBER() OVER (PARTITION BY m.unified_code ORDER BY e.available_time DESC, e.processing_time DESC, e.record_id DESC) AS position",
  "  FROM fund_metadata_observations m",
  "  JOIN fund_observation_evidence e ON e.record_id = m.evidence_id",
  "  WHERE m.payload ->> 'fundAssetClass' = 'PRECIOUS_METALS'",
  "    AND e.available_time <= $1::timestamptz",
  "    AND e.processing_time <= $1::timestamptz",
  "    AND (m.payload ->> 'validFrom')::date <= ($1::timestamptz AT TIME ZONE 'Asia/Shanghai')::date",
  "    AND (m.payload ->> 'validTo' IS NULL OR (m.payload ->> 'validTo')::date >= ($1::timestamptz AT TIME ZONE 'Asia/Shanghai')::date)",
  ")",
  "SELECT payload, event_time, available_time, processing_time, source_version, evidence_id",
  "FROM visible WHERE position = 1 ORDER BY payload ->> 'unifiedCode'",
].join("\n");

export const PRECIOUS_METALS_REFERENCE_PIT_SQL = [
  "WITH visible AS (",
  "  SELECT 'NAV'::text AS kind, n.unified_code, n.reference_date, n.value::text AS value,",
  "         e.event_time, e.available_time, e.processing_time, e.source,",
  "         COALESCE(e.source_revision, e.schema_version || '+' || e.normalizer_version) AS source_version,",
  "         e.record_id AS evidence_id,",
  "         ROW_NUMBER() OVER (PARTITION BY n.unified_code ORDER BY n.reference_date DESC, e.available_time DESC, e.processing_time DESC, e.record_id DESC) AS position",
  "  FROM fund_nav_observations n",
  "  JOIN fund_observation_evidence e ON e.record_id = n.evidence_id",
  "  WHERE e.available_time <= $1::timestamptz AND e.processing_time <= $1::timestamptz",
  "  UNION ALL",
  "  SELECT 'INAV'::text AS kind, n.unified_code, n.reference_date, n.value::text AS value,",
  "         e.event_time, e.available_time, e.processing_time, e.source,",
  "         COALESCE(e.source_revision, e.schema_version || '+' || e.normalizer_version) AS source_version,",
  "         e.record_id AS evidence_id,",
  "         ROW_NUMBER() OVER (PARTITION BY n.unified_code ORDER BY n.reference_date DESC, e.available_time DESC, e.processing_time DESC, e.record_id DESC) AS position",
  "  FROM fund_inav_observations n",
  "  JOIN fund_observation_evidence e ON e.record_id = n.evidence_id",
  "  WHERE e.available_time <= $1::timestamptz AND e.processing_time <= $1::timestamptz",
  ")",
  "SELECT kind, unified_code, reference_date, value, event_time, available_time, processing_time, source, source_version, evidence_id",
  "FROM visible WHERE position = 1 AND unified_code = ANY($2::text[])",
  "ORDER BY unified_code, kind",
].join("\n");

export const PRECIOUS_METALS_EVENT_PIT_SQL = [
  "SELECT payload FROM market_events",
  "WHERE instrument_ids ?| $1::text[]",
  "  AND available_time <= $2::timestamptz",
  "  AND (payload -> 'modelProvenance' ->> 'processingTime')::timestamptz <= $2::timestamptz",
  "ORDER BY available_time DESC, event_id",
  "LIMIT 100",
].join("\n");

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid precious-metals metadata payload");
  }
  return value as Record<string, unknown>;
}

function text(value: Record<string, unknown>, field: string): string {
  const candidate = value[field];
  if (typeof candidate !== "string" || candidate === "") {
    throw new Error("invalid precious-metals metadata field: " + field);
  }
  return candidate;
}

function parseFund(value: unknown): PreciousMetalFund {
  const input = object(value);
  const unifiedCode = text(input, "unifiedCode");
  if (!/^[0-9]{6}\.(SH|SZ|BJ)$/.test(unifiedCode)) {
    throw new Error("invalid precious-metals metadata field: unifiedCode");
  }
  if (input["fundAssetClass"] !== "PRECIOUS_METALS") {
    throw new Error("invalid precious-metals metadata field: fundAssetClass");
  }
  if (!new Set(["GOLD", "SILVER", "OTHER"]).has(String(input["underlyingCommodity"]))) {
    throw new Error("invalid precious-metals metadata field: underlyingCommodity");
  }
  if (!new Set(["ETF", "LOF", "FUND"]).has(String(input["assetType"]))) {
    throw new Error("invalid precious-metals metadata field: assetType");
  }
  if (input["tradingCurrency"] !== "CNY") {
    throw new Error("invalid precious-metals metadata field: tradingCurrency");
  }
  for (const field of [
    "navCurrency",
    "benchmarkOrTrackingIndex",
    "source",
    "availableTime",
    "processingTime",
    "rawObjectId",
  ]) {
    text(input, field);
  }
  const managementFeeRate = input["managementFeeRate"];
  const confidence = input["confidence"];
  if (typeof managementFeeRate !== "number" || managementFeeRate < 0 || managementFeeRate > 1) {
    throw new Error("invalid precious-metals metadata field: managementFeeRate");
  }
  if (typeof confidence !== "number" || confidence < 0 || confidence > 1) {
    throw new Error("invalid precious-metals metadata field: confidence");
  }
  if (input["reviewStatus"] !== "REVIEWED" && input["reviewStatus"] !== "NEEDS_REVIEW") {
    throw new Error("invalid precious-metals metadata field: reviewStatus");
  }
  return input as unknown as PreciousMetalFund;
}

function instant(value: Date | string, field: string): string {
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.getTime())) throw new Error("invalid PostgreSQL timestamp: " + field);
  return parsed.toISOString();
}

function optionalInstant(value: Date | string | null): string | null {
  return value === null ? null : instant(value, "event_time");
}

function dateOnly(value: Date | string): string {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return instant(value, "reference_date").slice(0, 10);
}

export class PostgresPreciousMetalsRepository implements PreciousMetalsPostgresReadModel {
  constructor(private readonly pool: Pick<Pool, "connect">) {}

  async load(asOf: string): Promise<PreciousMetalsPostgresContext> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
      const metadataResult = await client.query<MetadataRow>(PRECIOUS_METALS_METADATA_PIT_SQL, [
        asOf,
      ]);
      const funds = metadataResult.rows.map((row): PreciousMetalsFundRecord => {
        const data = parseFund(row.payload);
        return {
          data,
          eventTime: optionalInstant(row.event_time) ?? data.eventTime ?? data.publishTime,
          availableTime: instant(row.available_time, "available_time"),
          processingTime: instant(row.processing_time, "processing_time"),
          sourceVersion: row.source_version,
          evidenceId: row.evidence_id,
        };
      });
      const instrumentIds = funds.map((record) => record.data.unifiedCode);
      const references =
        instrumentIds.length === 0
          ? []
          : (
              await client.query<ReferenceRow>(PRECIOUS_METALS_REFERENCE_PIT_SQL, [
                asOf,
                instrumentIds,
              ])
            ).rows.map((row): PreciousMetalsReferenceRecord => ({
              kind: row.kind,
              instrumentId: row.unified_code,
              referenceDate: dateOnly(row.reference_date),
              value: row.value,
              eventTime: optionalInstant(row.event_time),
              availableTime: instant(row.available_time, "available_time"),
              processingTime: instant(row.processing_time, "processing_time"),
              source: row.source,
              sourceVersion: row.source_version,
              evidenceId: row.evidence_id,
            }));
      const events =
        instrumentIds.length === 0
          ? []
          : (
              await client.query<EventRow>(PRECIOUS_METALS_EVENT_PIT_SQL, [instrumentIds, asOf])
            ).rows.map((row): PreciousMetalsEventRecord => {
              const event = validateMarketEventPayload(row.payload);
              return {
                eventId: event.eventId,
                instrumentIds: event.instrumentIds.filter((id) => instrumentIds.includes(id)),
                eventType: event.eventType,
                headline: event.headline,
                summary: event.summary,
                publishTime: event.publishTime,
                availableTime: event.availableTime,
                processingTime: event.modelProvenance.processingTime,
                confidenceBps: event.confidenceBps,
                modelVersion: event.modelProvenance.modelVersion,
                sourceVersions: [
                  event.modelProvenance.provider + "@" + event.modelProvenance.modelVersion,
                  ...event.evidence.map(
                    (evidence) => evidence.sourceId + "@" + evidence.sourceVersion,
                  ),
                ],
                evidenceIds: event.evidence.map((evidence) => evidence.evidenceId),
              };
            });
      await client.query("COMMIT");
      return { funds, references, events };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }
}

export type PreciousMetalsPostgresClient = Pick<PoolClient, "query" | "release">;
