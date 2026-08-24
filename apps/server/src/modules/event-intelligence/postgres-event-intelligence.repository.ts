import type { HotTopicSnapshot, MarketEvent } from "@kunlun/shared-types";
import type { Pool } from "pg";
import type { EventIntelligenceRepository } from "./event-intelligence-repository";
import {
  type EventQuery,
  type HotTopicQuery,
  validateHotTopicPayload,
  validateMarketEventPayload,
} from "./event-intelligence-validation";

interface PayloadRow {
  payload: unknown;
}

const EVENT_SQL = `SELECT payload FROM market_events
WHERE ($1::date IS NULL OR available_time >= $1::date)
AND ($2::date IS NULL OR available_time < ($2::date + INTERVAL '1 day'))
AND ($3::text IS NULL OR event_type = $3)
AND ($4::text IS NULL OR instrument_ids ? $4)
AND ($5::integer IS NULL OR confidence_bps >= $5)
ORDER BY available_time DESC, event_id ASC LIMIT $6`;

const TOPIC_SQL = `SELECT payload FROM (
  SELECT DISTINCT ON (topic_id) topic_id, decision_time, score_bps, lifecycle, payload
  FROM hot_topic_snapshots
  WHERE decision_time <= $1::timestamptz
  ORDER BY topic_id, decision_time DESC, snapshot_id ASC
) latest
WHERE ($2::text IS NULL OR lifecycle = $2)
AND ($3::integer IS NULL OR score_bps >= $3)
ORDER BY score_bps DESC, topic_id ASC LIMIT $4`;

export class PostgresEventIntelligenceRepository implements EventIntelligenceRepository {
  constructor(private readonly pool: Pool) {}

  async queryEvents(query: EventQuery): Promise<MarketEvent[]> {
    const result = await this.pool.query<PayloadRow>(EVENT_SQL, [
      query.dateFrom ?? null,
      query.dateTo ?? null,
      query.eventType ?? null,
      query.instrumentId ?? null,
      query.minimumConfidenceBps ?? null,
      query.limit,
    ]);
    return result.rows.map((row) => validateMarketEventPayload(row.payload));
  }

  async queryHotTopics(query: HotTopicQuery): Promise<HotTopicSnapshot[]> {
    const result = await this.pool.query<PayloadRow>(TOPIC_SQL, [
      query.asOf,
      query.lifecycle ?? null,
      query.minimumScoreBps ?? null,
      query.limit,
    ]);
    return result.rows.map((row) => validateHotTopicPayload(row.payload));
  }
}
