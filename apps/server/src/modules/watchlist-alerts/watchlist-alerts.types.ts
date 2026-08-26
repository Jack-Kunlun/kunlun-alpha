import type { WatchlistAlertsWorkspace } from "@kunlun/shared-types";

export type WatchlistAlertRule = WatchlistAlertsWorkspace["rules"][number];
export type WatchlistAlertHistory = WatchlistAlertsWorkspace["history"][number];
export type WatchlistAlertField = WatchlistAlertRule["condition"]["field"];
export type WatchlistAlertOperator = WatchlistAlertRule["condition"]["operator"];

export interface CreateWatchlistAlertRuleInput {
  clientRequestId: string;
  name: string;
  enabled: boolean;
  instrumentIds: WatchlistAlertRule["instrumentIds"];
  condition: WatchlistAlertRule["condition"];
  quietPeriod: WatchlistAlertRule["quietPeriod"];
  throttleSeconds: number;
  notificationChannel: "IN_APP";
}

export interface ToggleWatchlistAlertRuleInput {
  clientRequestId: string;
  enabled: boolean;
}

export interface EvaluateWatchlistAlertInput {
  ruleId: string;
  eventId: string;
  instrumentId: string;
  field: WatchlistAlertField;
  featureName: string | null;
  observedValue: string;
  eventTime: string;
  availableTime: string;
}

export interface StoredWatchlistAlertRule {
  ownerRef: string;
  commandRequestId: string;
  commandHash: string;
  rule: WatchlistAlertRule;
}

export interface NotificationEnvelope {
  notificationId: string;
  historyId: string;
  ownerRef: string;
  title: string;
  body: string;
  availableAt: string;
}

export interface AppendHistoryResult {
  history: WatchlistAlertHistory;
  duplicate: boolean;
}

export interface AlertPreview {
  outcome: WatchlistAlertHistory["outcome"];
  detail: string;
}
