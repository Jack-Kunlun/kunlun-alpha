import { apiClient } from "@/lib/api-client";
import { useApiQuery, type QueryResult } from "@/lib/use-api-query";
import type {
  HotTopicSnapshot,
  MarketEmotionSnapshot,
  MarketEvent,
  RotationTerminalData,
  RotationTerminalResult,
  SectorRotationEvent,
} from "./types";

const SNAPSHOT_PATH = "/v1/emotion/snapshots";
const ROTATION_PATH = "/v1/emotion/rotation-events";
const EVENT_PATH = "/v1/event-intelligence/events";
const TOPIC_PATH = "/v1/event-intelligence/hot-topics";
const TOPIC_LIMIT = 100;

export interface RotationTerminalFilters {
  date: string;
  asOf: string;
  algorithmVersion?: string;
  sectorId?: string;
  lifecycle?: HotTopicSnapshot["lifecycle"];
}

export interface RotationTerminalQueries {
  replay: Record<string, string>;
  topics: Record<string, string>;
}

export interface MarketEventEvidenceQuery extends Record<string, string> {
  eventIds: string;
  asOf: string;
  limit: string;
}

export function rotationTerminalQueries(filters: RotationTerminalFilters): RotationTerminalQueries {
  const replay: Record<string, string> = { date: filters.date, asOf: filters.asOf };
  if (filters.algorithmVersion) replay.algorithmVersion = filters.algorithmVersion;
  if (filters.sectorId) replay.sectorId = filters.sectorId;
  const topics: Record<string, string> = { asOf: filters.asOf, limit: String(TOPIC_LIMIT) };
  if (filters.lifecycle) topics.lifecycle = filters.lifecycle;
  return {
    replay,
    topics,
  };
}

export function marketEventEvidenceQueries(
  topics: readonly HotTopicSnapshot[],
  asOf: string,
  batchSize = 100,
): MarketEventEvidenceQuery[] {
  const eventIds = [...new Set(topics.flatMap((topic) => topic.eventIds))].sort();
  const queries: MarketEventEvidenceQuery[] = [];
  for (let index = 0; index < eventIds.length; index += batchSize) {
    const batch = eventIds.slice(index, index + batchSize);
    queries.push({ eventIds: batch.join(","), asOf, limit: String(batch.length) });
  }
  return queries;
}

function available<T>(result: QueryResult<T>): T[] {
  return result.status === "success" || result.status === "empty" ? (result.data ?? []) : [];
}

function atOrBefore(value: string, cutoff: number): boolean {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && timestamp <= cutoff;
}

export function combineRotationTerminalResults(
  snapshotsResult: QueryResult<MarketEmotionSnapshot>,
  rotationResult: QueryResult<SectorRotationEvent>,
  topicsResult: QueryResult<HotTopicSnapshot>,
  eventsResult: QueryResult<MarketEvent>,
  asOf: string,
): RotationTerminalResult {
  const sources = [snapshotsResult, rotationResult, topicsResult, eventsResult] as const;
  const forbidden = sources.find((source) => source.status === "forbidden");
  if (forbidden) {
    return { status: "forbidden", data: null, error: forbidden.error, continuity: [] };
  }
  if (sources.some((source) => source.status === "loading")) {
    return { status: "loading", data: null, error: null, continuity: [] };
  }
  const cutoff = Date.parse(asOf);
  if (!Number.isFinite(cutoff)) {
    return {
      status: "error",
      data: null,
      error: new Error("回放点不是有效时间"),
      continuity: [],
    };
  }

  const rawSnapshots = available(snapshotsResult);
  const rawRotations = available(rotationResult);
  const rawTopics = available(topicsResult);
  const rawEvents = available(eventsResult);
  const snapshots = rawSnapshots.filter((snapshot) => atOrBefore(snapshot.timestamp, cutoff));
  const rotationEvents = rawRotations.filter(
    (event) => atOrBefore(event.timestamp, cutoff) && atOrBefore(event.evidenceEnd, cutoff),
  );
  const hotTopics = rawTopics.filter((topic) => atOrBefore(topic.decisionTime, cutoff));
  const marketEvents = rawEvents.filter((event) => atOrBefore(event.availableTime, cutoff));
  const continuity: string[] = [];
  const sourceErrors = [
    ["情绪快照", snapshotsResult],
    ["轮动事件", rotationResult],
    ["热点快照", topicsResult],
    ["结构化事件", eventsResult],
  ] as const;
  for (const [label, result] of sourceErrors) {
    if (result.status === "error") continuity.push(`${label}数据源中断`);
  }
  const excluded =
    rawSnapshots.length -
    snapshots.length +
    (rawRotations.length - rotationEvents.length) +
    (rawTopics.length - hotTopics.length) +
    (rawEvents.length - marketEvents.length);
  if (excluded > 0) continuity.push(`已按回放点截断 ${excluded} 条未来或无效记录`);
  const topicLimitReached = rawTopics.length >= TOPIC_LIMIT;
  if (topicLimitReached) {
    continuity.push(`热点快照已达到 ${TOPIC_LIMIT} 条查询上限，生命周期统计可能不完整`);
  }
  const visibleEventIds = new Set(marketEvents.map((event) => event.eventId));
  const unresolved = new Set(
    hotTopics.flatMap((topic) => topic.eventIds.filter((eventId) => !visibleEventIds.has(eventId))),
  );
  if (unresolved.size > 0) {
    continuity.push(
      `有 ${unresolved.size} 条热点事件证据未由点时查询返回（可能尚不可得或记录缺失）`,
    );
  }

  const data: RotationTerminalData = {
    asOf,
    snapshots,
    rotationEvents,
    hotTopics,
    marketEvents,
  };
  const recordCount =
    snapshots.length + rotationEvents.length + hotTopics.length + marketEvents.length;
  const error = sources.find((source) => source.status === "error")?.error ?? null;
  if (recordCount === 0) {
    return {
      status: error === null ? "empty" : "error",
      data: error === null ? data : null,
      error,
      continuity,
    };
  }
  return {
    status: error === null && !topicLimitReached ? "success" : "partial",
    data,
    error,
    continuity,
  };
}

export function useRotationTerminal(filters: RotationTerminalFilters): RotationTerminalResult {
  const query = rotationTerminalQueries(filters);
  const replayDependencies = [
    filters.date,
    filters.asOf,
    filters.algorithmVersion,
    filters.sectorId,
  ];
  const snapshots = useApiQuery(
    () => apiClient.get<MarketEmotionSnapshot[]>(SNAPSHOT_PATH, query.replay),
    replayDependencies,
  );
  const rotations = useApiQuery(
    () => apiClient.get<SectorRotationEvent[]>(ROTATION_PATH, query.replay),
    replayDependencies,
  );
  const topics = useApiQuery(
    () => apiClient.get<HotTopicSnapshot[]>(TOPIC_PATH, query.topics),
    [filters.asOf, filters.lifecycle],
  );
  const evidenceQueries = marketEventEvidenceQueries(available(topics), filters.asOf);
  const evidenceDependency = evidenceQueries.map((request) => request.eventIds).join("|");
  const events = useApiQuery(async () => {
    const batches = await Promise.all(
      evidenceQueries.map((request) => apiClient.get<MarketEvent[]>(EVENT_PATH, request)),
    );
    return batches.flat();
  }, [filters.asOf, evidenceDependency]);
  return combineRotationTerminalResults(snapshots, rotations, topics, events, filters.asOf);
}
