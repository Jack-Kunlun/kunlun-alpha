import { renderToStaticMarkup as renderMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { PaperPreviewDrawer, PaperPreviewResult } from "./paper-preview-drawer";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { capturePaperRiskContext, readPaperRiskPreview } from "./paper-risk-preview";

describe("paper preview presentation", () => {
  it("shows ten checks with a closed execution blocker and supports busy and retry states", () => {
    const raw: unknown = JSON.parse(
      readFileSync(
        resolve(process.cwd(), "../../data/fixtures/paper-risk-preview-v1.json"),
        "utf8",
      ),
    );
    const data = raw as Record<string, unknown>;
    const risk = readPaperRiskPreview(data.risk, capturePaperRiskContext(data.allocation));
    const result = {
      kind: "target" as const,
      time: risk.time,
      instrumentId: "600519.SH",
      policyVersion: "1.0.0",
      current: 0,
      target: 300,
      quantity: 300,
      side: "BUY" as const,
      price: "100",
      weight: "0.3",
      notional: "30000",
    };
    const html = renderToStaticMarkup(
      <PaperPreviewResult result={result} risk={risk} onRiskCheck={() => {}} />,
    );
    expect(html).toContain('href="/instruments/600519.SH"');
    expect(html).toContain("未开放");
    expect(html).toContain("存在阻断");
    expect(html).toContain("不改变账本");
    expect(html).not.toContain("EXECUTION_CONNECTED");
    expect(html).not.toContain("确认下单");
    const busy = renderToStaticMarkup(
      <PaperPreviewResult result={result} riskPending onRiskCheck={() => {}} />,
    );
    expect(busy).toContain('disabled=""');
    expect(busy).toContain('aria-busy="true"');
    expect(busy).toContain("disabled:cursor-progress");
    const retry = renderToStaticMarkup(
      <PaperPreviewResult result={result} riskError="检查暂不可用" onRiskCheck={() => {}} />,
    );
    expect(retry).toContain("重试风险检查");
    expect(retry).toContain("30000");
    expect(retry).toContain('role="alert"');
  });
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

function renderToStaticMarkup(node: ReactNode): string {
  return renderMarkup(<MemoryRouter>{node}</MemoryRouter>);
}
