import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import type * as ReactRouter from "react-router";
import { describe, expect, it, vi } from "vitest";
import { terminalRoutes } from "./app/route-contract";

let route = "/data-quality";

vi.mock("react-router", async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ReactRouter;
  return {
    ...actual,
    BrowserRouter: ({ children }: { children: React.ReactNode }) => (
      <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
    ),
  };
});

vi.mock("./features/data-quality/data-quality-page", () => ({
  DataQualityPage: () => <div>DATA_QUALITY_PAGE_MARKER</div>,
}));
vi.mock("./features/market-regime/market-regime-page", () => ({
  MarketRegimePage: () => <div>MARKET_REGIME_PAGE_MARKER</div>,
}));
vi.mock("./features/event-workbench/event-workbench-page", () => ({
  EventWorkbenchPage: () => <div>EVENT_WORKBENCH_PAGE_MARKER</div>,
}));
vi.mock("./features/seat-kol/seat-kol-workbench-page", () => ({
  SeatKolWorkbenchPage: () => <div>SEAT_KOL_WORKBENCH_MARKER</div>,
}));
vi.mock("./features/backtest/backtest-regression-page", () => ({
  BacktestRegressionPage: () => <div>BACKTEST_REGRESSION_MARKER</div>,
}));
vi.mock("./components/ui/sonner", () => ({ Toaster: () => null }));

import { App } from "./App";

describe("App routing", () => {
  it("serves the data-quality page", () => {
    route = "/data-quality";
    expect(renderToStaticMarkup(<App roles={["platform_admin"]} />)).toContain(
      "DATA_QUALITY_PAGE_MARKER",
    );
  });

  it("serves the persisted market-regime replay page", () => {
    route = "/market-regime";
    expect(renderToStaticMarkup(<App roles={["platform_admin"]} />)).toContain(
      "MARKET_REGIME_PAGE_MARKER",
    );
  });

  it("serves the Phase 3 event workbench", () => {
    route = "/event-workbench";
    expect(renderToStaticMarkup(<App roles={["platform_admin"]} />)).toContain(
      "EVENT_WORKBENCH_PAGE_MARKER",
    );
  });

  it("serves the Phase 4 Seat and KOL workbench", () => {
    route = "/seat-kol";
    expect(renderToStaticMarkup(<App roles={["platform_admin"]} />)).toContain(
      "SEAT_KOL_WORKBENCH_MARKER",
    );
  });

  it("keeps planned deep links stable without fabricating feature data", () => {
    route = "/precious-metals";
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain("ROUTE_PLACEHOLDER:precious-metals");
    expect(html).toContain("规划能力");
    expect(html).toContain("路由已就绪");
  });

  it("supports dynamic instrument deep links", () => {
    route = "/instruments/600519.SH";
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain("正在装配个股 Intelligence");
    expect(html).not.toContain("ROUTE_PLACEHOLDER:instrument-detail");
  });

  it("renders a controlled forbidden state for direct unauthorized access", () => {
    route = "/data-quality";
    const html = renderToStaticMarkup(<App roles={["viewer"]} />);
    expect(html).toContain("FORBIDDEN_ROUTE");
    expect(html).not.toContain("DATA_QUALITY_PAGE_MARKER");
  });

  it("renders keyboard and narrow-screen navigation semantics", () => {
    route = "/";
    const html = renderToStaticMarkup(<App roles={["viewer"]} />);
    expect(html).toContain('href="#terminal-main"');
    expect(html).toContain('aria-label="桌面主导航"');
    expect(html).toContain('aria-label="移动端主导航"');
    expect(html).toContain("打开主导航");
  });

  it("keeps unknown deep links on the navigable 404 page", () => {
    route = "/not-a-terminal-route";
    expect(renderToStaticMarkup(<App />)).toContain("404");
  });

  it("registers every route contract through the generated router", () => {
    for (const contract of terminalRoutes) {
      route = contract.href.replace("600519.SH", "000001.SZ");
      expect(renderToStaticMarkup(<App roles={["platform_admin"]} />)).not.toContain("页面不存在");
    }
  });

  it("preserves point-in-time and instrument filters across module navigation", () => {
    route = "/market-overview?asOf=2026-08-24T07%3A00%3A00.000Z&instrument=600519.SH";
    const html = renderToStaticMarkup(<App roles={["viewer"]} />);
    expect(html).toContain("上下文 1 标的");
    expect(html).toContain("/ranking?asOf=2026-08-24T07%3A00%3A00.000Z");
    expect(html).toContain("instrument=600519.SH");
  });
});
