import type { HotTopicSnapshot, MarketEvent } from "@kunlun/shared-types";
import type { EventIntelligenceRepository } from "./event-intelligence-repository";
import type { EventQuery, HotTopicQuery } from "./event-intelligence-validation";

export class InMemoryEventIntelligenceRepository implements EventIntelligenceRepository {
  constructor(
    private readonly events: MarketEvent[] = [],
    private readonly topics: HotTopicSnapshot[] = [],
  ) {}

  async queryEvents(query: EventQuery): Promise<MarketEvent[]> {
    return [...this.events]
      .filter((event) => {
        const date = event.availableTime.slice(0, 10);
        return (
          (query.dateFrom === undefined || date >= query.dateFrom) &&
          (query.dateTo === undefined || date <= query.dateTo) &&
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
    for (const topic of this.topics) {
      if (topic.decisionTime > query.asOf) continue;
      const current = latest.get(topic.topicId);
      if (!current || topic.decisionTime > current.decisionTime) latest.set(topic.topicId, topic);
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
