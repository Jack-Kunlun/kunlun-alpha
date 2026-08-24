import { Module } from "@nestjs/common";
import { Pool } from "pg";
import { EventIntelligenceController } from "./event-intelligence.controller";
import type { EventIntelligenceRepository } from "./event-intelligence-repository";
import {
  AllowAllEventIntelligenceAuthorizer,
  EventIntelligenceService,
} from "./event-intelligence.service";
import {
  EVENT_INTELLIGENCE_AUTHORIZER,
  EVENT_INTELLIGENCE_REPOSITORY,
} from "./event-intelligence.tokens";
import { PostgresEventIntelligenceRepository } from "./postgres-event-intelligence.repository";

function buildRepository(): EventIntelligenceRepository {
  const dsn = process.env["EVENT_INTELLIGENCE_POSTGRES_DSN"];
  if (!dsn) throw new Error("EVENT_INTELLIGENCE_POSTGRES_DSN is required for event intelligence");
  return new PostgresEventIntelligenceRepository(new Pool({ connectionString: dsn }));
}

@Module({
  controllers: [EventIntelligenceController],
  providers: [
    { provide: EVENT_INTELLIGENCE_REPOSITORY, useFactory: buildRepository },
    {
      provide: EVENT_INTELLIGENCE_AUTHORIZER,
      useClass: AllowAllEventIntelligenceAuthorizer,
    },
    EventIntelligenceService,
  ],
  exports: [EventIntelligenceService],
})
export class EventIntelligenceModule {}
