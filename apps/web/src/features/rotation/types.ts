import type {
  HotTopicSnapshot,
  MarketEmotionSnapshot,
  MarketEvent,
  SectorRotationEvent,
} from "@kunlun/shared-types";

export type { HotTopicSnapshot, MarketEmotionSnapshot, MarketEvent, SectorRotationEvent };

export interface RotationTerminalData {
  asOf: string;
  snapshots: MarketEmotionSnapshot[];
  rotationEvents: SectorRotationEvent[];
  hotTopics: HotTopicSnapshot[];
  marketEvents: MarketEvent[];
}

export type RotationTerminalStatus =
  "loading" | "empty" | "error" | "forbidden" | "partial" | "success";

export interface RotationTerminalResult {
  status: RotationTerminalStatus;
  data: RotationTerminalData | null;
  error: Error | null;
  continuity: string[];
}
