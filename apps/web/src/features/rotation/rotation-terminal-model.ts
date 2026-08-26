import type {
  HotTopicSnapshot,
  MarketEvent,
  RotationTerminalData,
  SectorRotationEvent,
} from "./types";

export const HOT_TOPIC_LIFECYCLE = [
  "EMERGING",
  "RISING",
  "HOT",
  "COOLING",
  "DORMANT",
] as const satisfies readonly HotTopicSnapshot["lifecycle"][];

export const HOT_TOPIC_LIFECYCLE_LABELS: Readonly<Record<HotTopicSnapshot["lifecycle"], string>> = {
  EMERGING: "萌芽",
  RISING: "升温",
  HOT: "炽热",
  COOLING: "降温",
  DORMANT: "沉寂",
};

export interface TopicComparisonRow {
  topicId: string;
  topicName: string;
  lifecycle: HotTopicSnapshot["lifecycle"];
  scoreBps: number;
  confidenceBps: number;
  eventCount: number;
  algorithmVersion: string;
}

export type TimelineKind = "rotation" | "topic" | "event";

export interface RotationTimelineItem {
  id: string;
  kind: TimelineKind;
  timestamp: string;
  title: string;
  marker: string;
  confidenceBps: number;
  scoreBps: number | null;
  algorithmVersion: string;
  sourceVersions: string[];
  evidenceIds: string[];
  relatedEventIds: string[];
  windowStart: string | null;
  windowEnd: string | null;
}

export function formatShanghaiTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间无效";
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(date)
      .map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

export function buildTopicComparison(
  topics: readonly HotTopicSnapshot[],
  limit = 8,
): TopicComparisonRow[] {
  return [...topics]
    .sort(
      (left, right) =>
        right.scoreBps - left.scoreBps ||
        right.confidenceBps - left.confidenceBps ||
        left.topicId.localeCompare(right.topicId),
    )
    .slice(0, limit)
    .map((topic) => ({
      topicId: topic.topicId,
      topicName: topic.topicName,
      lifecycle: topic.lifecycle,
      scoreBps: topic.scoreBps,
      confidenceBps: topic.confidenceBps,
      eventCount: topic.eventCount,
      algorithmVersion: topic.algorithmVersion,
    }));
}

function rotationItem(event: SectorRotationEvent): RotationTimelineItem {
  return {
    id: event.eventId,
    kind: "rotation",
    timestamp: event.timestamp,
    title: `${event.fromSector ?? "新主线"} → ${event.toSector}`,
    marker: event.eventType === "CROSSOVER" ? "交叉切换" : "轮动衰减",
    confidenceBps: Math.round(event.confidence * 10_000),
    scoreBps: null,
    algorithmVersion: event.algorithmVersion,
    sourceVersions: event.sourceVersions,
    evidenceIds: event.evidenceIds,
    relatedEventIds: [],
    windowStart: event.evidenceStart,
    windowEnd: event.evidenceEnd,
  };
}

function topicItem(topic: HotTopicSnapshot): RotationTimelineItem {
  return {
    id: topic.snapshotId,
    kind: "topic",
    timestamp: topic.decisionTime,
    title: topic.topicName,
    marker: `热点${HOT_TOPIC_LIFECYCLE_LABELS[topic.lifecycle]}`,
    confidenceBps: topic.confidenceBps,
    scoreBps: topic.scoreBps,
    algorithmVersion: topic.algorithmVersion,
    sourceVersions: [`policy:${topic.policyFingerprint.slice(0, 12)}`],
    evidenceIds: [],
    relatedEventIds: topic.eventIds,
    windowStart: topic.windowStart,
    windowEnd: topic.windowEnd,
  };
}

function eventItem(event: MarketEvent): RotationTimelineItem {
  return {
    id: event.eventId,
    kind: "event",
    timestamp: event.availableTime,
    title: event.headline,
    marker: `事件 ${event.eventType}`,
    confidenceBps: event.confidenceBps,
    scoreBps: null,
    algorithmVersion: `${event.modelProvenance.modelVersion}/${event.modelProvenance.promptVersion}`,
    sourceVersions: [...new Set(event.evidence.map((item) => item.sourceVersion))],
    evidenceIds: event.evidence.map((item) => item.evidenceId),
    relatedEventIds: [event.eventId],
    windowStart: event.occurTime,
    windowEnd: event.availableTime,
  };
}

export function buildRotationTimeline(data: RotationTerminalData): RotationTimelineItem[] {
  return [
    ...data.rotationEvents.map(rotationItem),
    ...data.hotTopics.map(topicItem),
    ...data.marketEvents.map(eventItem),
  ].sort(
    (left, right) =>
      Date.parse(right.timestamp) - Date.parse(left.timestamp) ||
      left.kind.localeCompare(right.kind) ||
      left.id.localeCompare(right.id),
  );
}
