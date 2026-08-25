import { ForbiddenException, Inject, Injectable } from "@nestjs/common";
import type { SeatKolWorkbenchSnapshot } from "@kunlun/shared-types";
import type { SeatKolWorkbenchRepository } from "./seat-kol-repository";
import { SEAT_KOL_WORKBENCH_AUTHORIZER, SEAT_KOL_WORKBENCH_REPOSITORY } from "./seat-kol.tokens";
import { validateSeatKolQuery } from "./seat-kol-validation";

export interface SeatKolWorkbenchAuthorizer {
  canRead(): Promise<boolean>;
}

export class AllowAllSeatKolWorkbenchAuthorizer implements SeatKolWorkbenchAuthorizer {
  async canRead(): Promise<true> {
    return true;
  }
}

@Injectable()
export class SeatKolWorkbenchService {
  constructor(
    @Inject(SEAT_KOL_WORKBENCH_REPOSITORY)
    private readonly repository: SeatKolWorkbenchRepository,
    @Inject(SEAT_KOL_WORKBENCH_AUTHORIZER)
    private readonly authorizer: SeatKolWorkbenchAuthorizer = new AllowAllSeatKolWorkbenchAuthorizer(),
  ) {}

  async workbench(query: unknown): Promise<SeatKolWorkbenchSnapshot[]> {
    if (!(await this.authorizer.canRead())) {
      throw new ForbiddenException("无权访问席位与 KOL 工作台");
    }
    const snapshot = await this.repository.latest(validateSeatKolQuery(query));
    return snapshot ? [snapshot] : [];
  }
}
