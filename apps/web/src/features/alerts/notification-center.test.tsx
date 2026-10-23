import type { InAppNotificationCenter } from "@kunlun/shared-types";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { NotificationCenterPanel } from "./notification-center";
import type { ComponentProps } from "react";
import { MemoryRouter } from "react-router";
import { TerminalFilterProvider } from "@/app/filter-context";

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

function renderPanel(overrides: Partial<ComponentProps<typeof NotificationCenterPanel>> = {}) {
  return renderToStaticMarkup(
    <MemoryRouter
      initialEntries={["/watchlists?asOf=2026-08-01T00%3A00%3A00.000Z&instrument=000001.SZ"]}
    >
      <TerminalFilterProvider>
        <NotificationCenterPanel
          center={center}
          loading={false}
          error={null}
          pending={false}
          filters={{ readStatus: "ALL", instrumentQuery: "" }}
          onFiltersChange={vi.fn()}
          onRefresh={vi.fn()}
          onRead={vi.fn()}
          onReadAll={vi.fn()}
          onNavigate={vi.fn()}
          {...overrides}
        />
      </TerminalFilterProvider>
    </MemoryRouter>,
  );
}

describe("NotificationCenterPanel", () => {
  it.each([null, "2026-08-30T02:00:00.000Z"])(
    "links both unread and read notifications without inheriting unrelated historical filters: %s",
    (readAt) => {
      const html = renderPanel({
        center: { ...center, notifications: [{ ...center.notifications[0]!, readAt }] },
      });
      expect(html).toContain('href="/instruments/600519.SH"');
      expect(html).toContain('aria-label="查看 600519.SH 标的日线"');
      expect(html).toContain('aria-describedby="notification-navigation-scope"');
      expect(html).toContain("当前查询时点");
      expect(html).toContain("不代表提醒触发时刻价格");
      expect(html).toContain("跳转不会标记已读");
      expect(html).not.toContain("/instruments/600519.SH?");
    },
  );

  it("keeps a malformed notification readable without an invalid navigation action", () => {
    const html = renderPanel({
      center: {
        ...center,
        notifications: [{ ...center.notifications[0]!, instrumentId: "00700.HK" }],
      },
    });
    expect(html).toContain("证券代码不符合日线格式，无法跳转");
    expect(html).not.toContain('href="/instruments/');
    expect(html).toContain("贵州茅台价格提醒");
    expect(html).toContain("标记已读");
  });

  it("renders unread persisted alerts and bounded read actions", () => {
    const html = renderPanel();

    expect(html).toContain("1 条未读");
    expect(html).toContain("贵州茅台价格提醒");
    expect(html).toContain("600519.SH");
    expect(html).toContain("标记已读");
    expect(html).toContain("全部通知已读");
    expect(html).toContain("仅站内研究提醒");
    expect(html).not.toMatch(/真实下单|broker/i);
  });

  it.each([
    { loading: true, pending: false },
    { loading: false, pending: true },
  ])("locks read actions during refresh or update: %j", ({ loading, pending }) => {
    const html = renderPanel({ loading, pending });
    expect(html).toContain('aria-busy="true"');
    for (const label of ["全部通知已读", "刷新通知", "标记已读"]) {
      expect(html).toMatch(
        new RegExp(`<button(?=[^>]*aria-label="${label}")(?=[^>]*disabled="")[^>]*>`),
      );
    }
    const busyLabel = loading ? "刷新通知" : "全部通知已读";
    expect(html).toMatch(
      new RegExp(
        `<button(?=[^>]*aria-label="${busyLabel}")(?=[^>]*aria-busy="true")(?=[^>]*cursor-progress)[^>]*>`,
      ),
    );
  });

  it("labels the recent scope and provides accessible controls with a reset", () => {
    const html = renderPanel();
    expect(html).toContain('for="notification-read-status"');
    expect(html).toContain('for="notification-instrument"');
    expect(html).toContain("最多 100 条");
    expect(html).toContain("近期匹配 1 / 1 条");
    expect(html).toContain("重置筛选");
    expect(html).toContain("不受筛选影响");
  });

  it("keeps the full unread count when the recent page has no matching unread notice", () => {
    const html = renderPanel({
      center: {
        ...center,
        unreadCount: 145,
        notifications: Array.from({ length: 100 }, (_, index) => ({
          ...center.notifications[0]!,
          notificationId: index.toString(16).padStart(64, "0"),
          readAt: "2026-10-23T00:00:00.000Z",
        })),
      },
      filters: { readStatus: "UNREAD", instrumentQuery: "" },
    });
    expect(html).toContain("145 条未读（全部通知）");
    expect(html).toContain("近期匹配 0 / 100 条");
    expect(html).toContain("近期通知中没有匹配项");
    expect(html).toContain("不代表本账号没有未读通知");
    expect(html).not.toContain("贵州茅台价格提醒");
  });

  it("distinguishes an empty recent response from a failed or unknown read", () => {
    const empty = renderPanel({ center: { ...center, unreadCount: 0, notifications: [] } });
    expect(empty).toContain("本次暂无近期通知");
    expect(empty).toContain("近期匹配 0 / 0 条");
    const failure = renderPanel({ center: null, error: "读取失败" });
    expect(failure).toContain("未读数未知");
    expect(failure).toContain("通知中心暂不可用");
    expect(failure).not.toContain("0 条未读");
    expect(failure).not.toContain("近期匹配");
  });

  it("preserves the applied filter on refresh and on error without reporting false emptiness", () => {
    for (const state of [{ loading: true }, { error: "读取失败" }]) {
      const html = renderPanel({
        ...state,
        filters: { readStatus: "READ", instrumentQuery: "600519.SH" },
      });
      expect(html).toContain('value="600519.SH"');
      expect(html).toContain('value="READ" selected=""');
      expect(html).toContain("上次读取");
      expect(html).not.toContain("近期通知中没有匹配项");
    }
  });
});
