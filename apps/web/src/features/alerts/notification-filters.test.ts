import type { InAppNotification } from "@kunlun/shared-types";
import { describe, expect, it } from "vitest";
import { filterRecentNotifications } from "./notification-filters";

function notification(
  id: string,
  instrumentId: string,
  readAt: string | null,
  deliveryStatus: InAppNotification["deliveryStatus"] = "DELIVERED",
): InAppNotification {
  return {
    schemaVersion: "in-app-notification-v1",
    notificationId: id.repeat(64),
    historyId: "d".repeat(64),
    ruleId: "e".repeat(64),
    instrumentId,
    title: "隔离测试提醒",
    body: "隔离测试正文",
    availableAt: "2026-10-23T00:00:00.000Z",
    deliveryStatus,
    deliveryAttempts: 1,
    readAt,
  };
}
const notices = [
  notification("a", "600519.SH", null, "FAILED"),
  notification("b", "000001.SZ", "2026-10-23T00:01:00.000Z"),
  notification("c", "600000.SH", null, "PENDING"),
];

describe("recent notification filters", () => {
  it("preserves server order and object identity without modifying input", () => {
    const before = structuredClone(notices);
    const result = filterRecentNotifications(notices, { readStatus: "ALL", instrumentQuery: "" });
    expect(result).toEqual(notices);
    expect(result[0]).toBe(notices[0]);
    expect(notices).toEqual(before);
  });

  it("uses read receipts independently of delivery status", () => {
    expect(
      filterRecentNotifications(notices, { readStatus: "UNREAD", instrumentQuery: "" }),
    ).toEqual([notices[0], notices[2]]);
    expect(filterRecentNotifications(notices, { readStatus: "READ", instrumentQuery: "" })).toEqual(
      [notices[1]],
    );
  });

  it("combines a trimmed case-insensitive code fragment with read status", () => {
    expect(
      filterRecentNotifications(notices, { readStatus: "UNREAD", instrumentQuery: " 600519.sh " }),
    ).toEqual([notices[0]]);
    expect(
      filterRecentNotifications(notices, { readStatus: "ALL", instrumentQuery: ".sh" }),
    ).toEqual([notices[0], notices[2]]);
    expect(
      filterRecentNotifications(notices, { readStatus: "READ", instrumentQuery: "600519" }),
    ).toEqual([]);
  });

  it("searches only security codes and treats search input literally", () => {
    expect(
      filterRecentNotifications(notices, { readStatus: "ALL", instrumentQuery: "隔离测试" }),
    ).toEqual([]);
    expect(
      filterRecentNotifications(notices, { readStatus: "ALL", instrumentQuery: ".*" }),
    ).toEqual([]);
  });

  it("returns no match for an empty response or a recent page containing only read notices", () => {
    expect(filterRecentNotifications([], { readStatus: "ALL", instrumentQuery: "" })).toEqual([]);
    const readPage = Array.from({ length: 100 }, () => notices[1]!);
    expect(
      filterRecentNotifications(readPage, { readStatus: "UNREAD", instrumentQuery: "" }),
    ).toEqual([]);
  });
});
