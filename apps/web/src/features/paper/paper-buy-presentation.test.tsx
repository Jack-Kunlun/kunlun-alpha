import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PaperBuyOrdersCard } from "./paper-buy-orders-card";
import { capturePaperRiskContext, readPaperRiskPreview } from "./paper-risk-preview";
import { PaperPreviewResult } from "./paper-preview-drawer";

function fixture(): Record<string, unknown> {
  const raw: unknown = JSON.parse(
    readFileSync(
      resolve(process.cwd(), "../../data/fixtures/paper-controlled-buy-v1.json"),
      "utf8",
    ),
  );
  if (typeof raw !== "object" || raw === null) throw new Error();
  return raw as Record<string, unknown>;
}
describe("controlled paper buy presentation", () => {
  it("shows exact filled records and fees with an accessible horizontal region", () => {
    const html = renderToStaticMarkup(<PaperBuyOrdersCard workspace={fixture().completed} />);
    expect(html).toContain("已模拟成交");
    expect(html).toContain("手续费（CNY）");
    expect(html).toContain("600519.SH");
    expect(html).toContain('tabindex="0"');
    expect(html).toContain("不代表真实行情");
    expect(html).not.toContain("FILLED");
  });
  it("offers the buy action only after bound risk passes, with native busy state", () => {
    const data = fixture();
    const risk = readPaperRiskPreview(data.risk, capturePaperRiskContext(data.allocation));
    expect(risk.allowed).toBe(true);
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
      <PaperPreviewResult result={result} risk={risk} onBuyOpen={() => {}} />,
    );
    expect(html).toContain("本次检查通过");
    expect(html).toContain(">模拟买入</button>");
    expect(
      renderToStaticMarkup(<PaperPreviewResult result={result} onBuyOpen={() => {}} />),
    ).not.toContain(">模拟买入</button>");
    const pending = renderToStaticMarkup(
      <PaperPreviewResult result={result} risk={risk} buyPending onBuyOpen={() => {}} />,
    );
    expect(pending).toContain('disabled=""');
    expect(pending).toContain("disabled:cursor-progress");
  });
});
