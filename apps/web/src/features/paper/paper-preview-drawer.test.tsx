import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PaperPreviewDrawer, PaperPreviewResult } from "./paper-preview-drawer";

describe("paper preview presentation", () => {
  it("keeps the scenario form behind an explicit action", () => {
    const html = renderToStaticMarkup(
      <PaperPreviewDrawer accountId={"a".repeat(64)} disabled={false} />,
    );
    expect(html).toContain("试算仓位");
    expect(html).toContain("cursor-pointer");
    expect(html).not.toContain("<form");
    expect(html).not.toContain("证券代码");
  });
  it("natively disables previews when the account is unavailable", () => {
    expect(
      renderToStaticMarkup(<PaperPreviewDrawer accountId={"a".repeat(64)} disabled />),
    ).toContain('disabled=""');
  });
  it("labels the calculated amount as an unexecuted manual hypothesis", () => {
    const html = renderToStaticMarkup(
      <PaperPreviewResult
        result={{
          kind: "target",
          time: "2026-10-25T02:00:00Z",
          instrumentId: "600519.SH",
          policyVersion: "1.0.0",
          current: 0,
          target: 300,
          quantity: 300,
          side: "BUY",
          price: "100",
          weight: "0.3",
          notional: "30000.0000000000000003",
        }}
      />,
    );
    expect(html).toContain("30000.0000000000000003");
    expect(html).toContain("未含费用");
    expect(html).toContain("账本未改变");
    expect(html).toContain("人工价格与信号假设");
    expect(html).not.toContain("确认下单");
    expect(html).not.toContain("FILLED");
    expect(html).not.toContain("brokerExecutable");
  });
});
