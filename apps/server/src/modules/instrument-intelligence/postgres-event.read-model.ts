import type { MarketEvent } from "@kunlun/shared-types";
import type { PoolClient, QueryResultRow } from "pg";
import { validateMarketEventPayload } from "../event-intelligence/event-intelligence-validation";
import type { PitRecord } from "./read-model.types";

interface EventRow extends QueryResultRow {
  payload: unknown;
}

const SQL = [
  "SELECT payload",
  "FROM market_events",
  "WHERE instrument_ids ? $1",
  "  AND available_time <= $2::timestamptz",
  "  AND (payload -> 'modelProvenance' ->> 'processingTime')::timestamptz <= $2::timestamptz",
  "ORDER BY available_time DESC, event_id",
  "LIMIT 100",
].join("\n");

export async function loadMarketEvents(
  client: Pick<PoolClient, "query">,
  instrumentId: string,
  asOf: string,
): Promise<PitRecord<MarketEvent>[]> {
  const result = await client.query<EventRow>(SQL, [instrumentId, asOf]);
  return result.rows.map((row) => {
    const data = validateMarketEventPayload(row.payload);
    return {
      data,
      eventTime: data.publishTime,
      availableTime: data.availableTime,
      processingTime: data.modelProvenance.processingTime,
      sourceVersions: [
        data.modelProvenance.provider + "@" + data.modelProvenance.modelVersion,
        ...data.evidence.map((item) => item.sourceId + "@" + item.sourceVersion),
      ],
      evidenceIds: data.evidence.map((item) => item.evidenceId),
    };
  });
}

export const MARKET_EVENT_INSTRUMENT_PIT_SQL = SQL;
