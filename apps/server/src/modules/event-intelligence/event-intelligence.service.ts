import { ForbiddenException, Inject, Injectable } from "@nestjs/common";
import type { HotTopicSnapshot, MarketEvent } from "@kunlun/shared-types";
import type { EventIntelligenceRepository } from "./event-intelligence-repository";
import { validateEventQuery, validateHotTopicQuery } from "./event-intelligence-validation";
import {
  EVENT_INTELLIGENCE_AUTHORIZER,
  EVENT_INTELLIGENCE_REPOSITORY,
} from "./event-intelligence.tokens";

export interface EventIntelligenceAuthorizer {
  canRead(): Promise<boolean>;
}

export class AllowAllEventIntelligenceAuthorizer implements EventIntelligenceAuthorizer {
  async canRead(): Promise<true> {
    return true;
  }
}

@Injectable()
export class EventIntelligenceService {
  constructor(
    @Inject(EVENT_INTELLIGENCE_REPOSITORY)
    private readonly repository: EventIntelligenceRepository,
    @Inject(EVENT_INTELLIGENCE_AUTHORIZER)
    private readonly authorizer: EventIntelligenceAuthorizer = new AllowAllEventIntelligenceAuthorizer(),
  ) {}

  async events(query: unknown): Promise<MarketEvent[]> {
    await this.authorized();
    return this.repository.queryEvents(validateEventQuery(query));
  }

  async hotTopics(query: unknown): Promise<HotTopicSnapshot[]> {
    await this.authorized();
    return this.repository.queryHotTopics(validateHotTopicQuery(query));
  }

  private async authorized(): Promise<void> {
    if (!(await this.authorizer.canRead())) throw new ForbiddenException("无权访问事件情报工作台");
  }
}
