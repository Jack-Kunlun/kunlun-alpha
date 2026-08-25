import type { SeatKolWorkbenchSnapshot } from "@kunlun/shared-types";
import type { SeatKolWorkbenchQuery } from "./seat-kol.types";

export interface SeatKolWorkbenchRepository {
  latest(query: SeatKolWorkbenchQuery): Promise<SeatKolWorkbenchSnapshot | null>;
}
