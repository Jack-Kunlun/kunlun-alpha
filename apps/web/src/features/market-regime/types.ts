import type { MarketEmotionSnapshot, SectorRotationEvent } from "@kunlun/shared-types";

export type { MarketEmotionSnapshot, SectorRotationEvent };

export interface MarketRegimeData {
  snapshots: MarketEmotionSnapshot[];
  events: SectorRotationEvent[];
}
