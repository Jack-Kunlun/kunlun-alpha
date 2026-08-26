import type { HotTopicSnapshot, MarketEvent } from "@kunlun/shared-types";
import type { EventIntelligenceRepository } from "./event-intelligence-repository";
import type { EventQuery, HotTopicQuery } from "./event-intelligence-validation";

function shanghaiDate(value: string): string {
  return new Date(Date.parse(value) + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

export class InMemoryEventIntelligenceRepository implements EventIntelligenceRepository {
  constructor(
    private readonly events: MarketEvent[] = [],
    private readonly topics: HotTopicSnapshot[] = [],
  ) {}

  async queryEvents(query: EventQuery): Promise<MarketEvent[]> {
    const eventIds = query.eventIds === undefined ? null : new Set(query.eventIds);
    const asOf = query.asOf === undefined ? null : Date.parse(query.asOf);
    return [...this.events]
      .filter((event) => {
        const date = shanghaiDate(event.availableTime);
        return (
          (query.dateFrom === undefined || date >= query.dateFrom) &&
          (query.dateTo === undefined || date <= query.dateTo) &&
          (eventIds === null || eventIds.has(event.eventId)) &&
          (asOf === null || Date.parse(event.availableTime) <= asOf) &&
          (query.eventType === undefined || event.eventType === query.eventType) &&
          (query.instrumentId === undefined || event.instrumentIds.includes(query.instrumentId)) &&
          (query.minimumConfidenceBps === undefined ||
            event.confidenceBps >= query.minimumConfidenceBps)
        );
      })
      .sort(
        (left, right) =>
          right.availableTime.localeCompare(left.availableTime) ||
          left.eventId.localeCompare(right.eventId),
      )
      .slice(0, query.limit);
  }

  async queryHotTopics(query: HotTopicQuery): Promise<HotTopicSnapshot[]> {
    const latest = new Map<string, HotTopicSnapshot>();
    const asOf = Date.parse(query.asOf);
    for (const topic of this.topics) {
      const decisionTime = Date.parse(topic.decisionTime);
      if (decisionTime > asOf) continue;
      const current = latest.get(topic.topicId);
      if (
        !current ||
        decisionTime > Date.parse(current.decisionTime) ||
        (decisionTime === Date.parse(current.decisionTime) && topic.snapshotId < current.snapshotId)
      ) {
        latest.set(topic.topicId, topic);
      }
    }
    return [...latest.values()]
      .filter(
        (topic) =>
          (query.lifecycle === undefined || topic.lifecycle === query.lifecycle) &&
          (query.minimumScoreBps === undefined || topic.scoreBps >= query.minimumScoreBps),
      )
      .sort(
        (left, right) =>
          right.scoreBps - left.scoreBps || left.topicId.localeCompare(right.topicId),
      )
      .slice(0, query.limit);
  }
}
