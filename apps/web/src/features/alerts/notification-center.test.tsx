import type { InAppNotificationCenter } from "@kunlun/shared-types";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { NotificationCenterPanel } from "./notification-center";

const center: InAppNotificationCenter = {
  schemaVersion: "in-app-notification-center-v1",
  generatedAt: "2026-08-30T02:00:00.000Z",
  unreadCount: 1,
  notifications: [
    {
      schemaVersion: "in-app-notification-v1",
      notificationId: "a".repeat(64),
      historyId: "b".repeat(64),
      ruleId: "c".repeat(64),
      instrumentId: "600519.SH",
      title: "贵州茅台价格提醒",
      body: "600519.SH LAST_PRICE GTE 1500.00",
      availableAt: "2026-08-30T01:59:00.000Z",
      deliveryStatus: "DELIVERED",
      deliveryAttempts: 1,
      readAt: null,
    },
  ],
  dataMeaning: "RESEARCH_IN_APP_ALERTS_NO_ORDER_PATH",
};

describe("NotificationCenterPanel", () => {
  it("renders unread persisted alerts and bounded read actions", () => {
    const html = renderToStaticMarkup(
      <NotificationCenterPanel
        center={center}
        loading={false}
        error={null}
        pending={false}
        onRefresh={vi.fn()}
        onRead={vi.fn()}
        onReadAll={vi.fn()}
      />,
    );

    expect(html).toContain("1 条未读");
    expect(html).toContain("贵州茅台价格提醒");
    expect(html).toContain("600519.SH");
    expect(html).toContain("标记已读");
    expect(html).toContain("全部已读");
    expect(html).toContain("仅站内研究提醒");
    expect(html).not.toMatch(/真实下单|broker/i);
  });
});
