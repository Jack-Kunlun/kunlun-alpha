import type { InAppNotification } from "@kunlun/shared-types";

export const NOTIFICATION_READ_STATUSES = [
  { value: "ALL", label: "全部状态" },
  { value: "UNREAD", label: "未读" },
  { value: "READ", label: "已读" },
] as const;

export interface RecentNotificationFilters {
  readonly readStatus: (typeof NOTIFICATION_READ_STATUSES)[number]["value"];
  readonly instrumentQuery: string;
}

export const DEFAULT_NOTIFICATION_FILTERS: RecentNotificationFilters = {
  readStatus: "ALL",
  instrumentQuery: "",
};

/** Only filters the returned recent collection; never derives the account-wide unread count. */
export function filterRecentNotifications(
  notifications: readonly InAppNotification[],
  filters: RecentNotificationFilters,
): InAppNotification[] {
  const code = filters.instrumentQuery.trim().toUpperCase();
  return notifications.filter(
    (item) =>
      (filters.readStatus === "ALL" ||
        (filters.readStatus === "UNREAD" ? item.readAt === null : item.readAt !== null)) &&
      item.instrumentId.toUpperCase().includes(code),
  );
}
