import { Module } from "@nestjs/common";
import {
  InMemorySeatKolWorkbenchRepository,
  LOCAL_PREVIEW_SEAT_KOL_SNAPSHOT,
} from "./in-memory-seat-kol.repository";
import { SeatKolWorkbenchController } from "./seat-kol.controller";
import { AllowAllSeatKolWorkbenchAuthorizer, SeatKolWorkbenchService } from "./seat-kol.service";
import { SEAT_KOL_WORKBENCH_AUTHORIZER, SEAT_KOL_WORKBENCH_REPOSITORY } from "./seat-kol.tokens";

function buildRepository(): InMemorySeatKolWorkbenchRepository {
  const snapshots =
    process.env["NODE_ENV"] === "production" ? [] : [LOCAL_PREVIEW_SEAT_KOL_SNAPSHOT];
  return new InMemorySeatKolWorkbenchRepository(snapshots);
}

@Module({
  controllers: [SeatKolWorkbenchController],
  providers: [
    { provide: SEAT_KOL_WORKBENCH_REPOSITORY, useFactory: buildRepository },
    { provide: SEAT_KOL_WORKBENCH_AUTHORIZER, useClass: AllowAllSeatKolWorkbenchAuthorizer },
    SeatKolWorkbenchService,
  ],
  exports: [SeatKolWorkbenchService],
})
export class SeatKolWorkbenchModule {}
