import type { HotTopicSnapshot, MarketEvent } from "@kunlun/shared-types";
import type { EventQuery, HotTopicQuery } from "./event-intelligence-validation";

export interface EventIntelligenceRepository {
  queryEvents(query: EventQuery): Promise<MarketEvent[]>;
  queryHotTopics(query: HotTopicQuery): Promise<HotTopicSnapshot[]>;
}
