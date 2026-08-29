import type { AuthSessionSummary } from "@kunlun/shared-types";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AccountSecurityPanel } from "./account-security-dialog";

const sessions: AuthSessionSummary[] = [
  {
    sessionId: "a".repeat(64),
    current: true,
    createdAt: "2026-08-29T08:00:00.000Z",
    lastSeenAt: "2026-08-29T08:10:00.000Z",
    idleExpiresAt: "2026-08-29T08:40:00.000Z",
    absoluteExpiresAt: "2026-08-29T16:00:00.000Z",
  },
  {
    sessionId: "b".repeat(64),
    current: false,
    createdAt: "2026-08-29T07:00:00.000Z",
    lastSeenAt: "2026-08-29T07:55:00.000Z",
    idleExpiresAt: "2026-08-29T08:25:00.000Z",
    absoluteExpiresAt: "2026-08-29T15:00:00.000Z",
  },
];

describe("AccountSecurityPanel", () => {
  it("renders password controls and distinguishes current from revocable sessions", () => {
    const html = renderToStaticMarkup(
      <AccountSecurityPanel
        sessions={sessions}
        sessionsLoading={false}
        sessionsError={null}
        revokingSessionId={null}
        passwordPending={false}
        onRefresh={async () => undefined}
        onRevoke={async () => undefined}
        onChangePassword={async () => true}
      />,
    );

    expect(html).toContain("修改密码");
    expect(html).toContain("当前密码");
    expect(html).toContain("新密码");
    expect(html).toContain("当前会话");
    expect(html).toContain("撤销会话");
    expect(html).toContain('autoComplete="current-password"');
    expect(html).toContain('autoComplete="new-password"');
  });
});
