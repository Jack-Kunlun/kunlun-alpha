import { renderToReadableStream, renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import type * as ReactRouter from "react-router";
import { describe, expect, it, vi } from "vitest";
import { terminalRoutes, type TerminalRole } from "./app/route-contract";

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
  DataQualityPage: () => <div>DEFERRED_FEATURE:data-quality</div>,
}));
vi.mock("./features/market-regime/market-regime-page", () => ({
  MarketRegimePage: () => <div>DEFERRED_FEATURE:market-regime</div>,
}));
vi.mock("./features/event-workbench/event-workbench-page", () => ({
  EventWorkbenchPage: () => <div>DEFERRED_FEATURE:event-workbench</div>,
}));
vi.mock("./features/seat-kol/seat-kol-workbench-page", () => ({
  SeatKolWorkbenchPage: () => <div>DEFERRED_FEATURE:seat-kol</div>,
}));
vi.mock("./features/backtest/backtest-regression-page", () => ({
  BacktestRegressionPage: () => <div>DEFERRED_FEATURE:backtest-regressions</div>,
}));
vi.mock("./features/precious-metals/precious-metals-terminal-page", () => ({
  PreciousMetalsTerminalPage: () => <div>DEFERRED_FEATURE:precious-metals</div>,
}));
vi.mock("./features/limit-pool/limit-pool-terminal-page", () => ({
  LimitPoolTerminalPage: () => <div>DEFERRED_FEATURE:limit-pool</div>,
}));
vi.mock("./features/rotation/rotation-terminal-page", () => ({
  RotationTerminalPage: () => <div>DEFERRED_FEATURE:rotation</div>,
}));
vi.mock("./features/ranking/ranking-terminal-page", () => ({
  RankingTerminalPage: () => <div>DEFERRED_FEATURE:ranking</div>,
}));
vi.mock("./features/paper/paper-terminal-page", () => ({
  PaperTerminalPage: () => <div>DEFERRED_FEATURE:paper</div>,
}));
vi.mock("./features/market-data-settings/market-data-settings-page", () => ({
  MarketDataSettingsPage: () => <div>DEFERRED_FEATURE:market-data-settings</div>,
}));
vi.mock("./components/ui/sonner", () => ({ Toaster: () => null }));

import { App } from "./App";

async function renderApp(roles?: readonly TerminalRole[]): Promise<string> {
  const stream = await renderToReadableStream(<App roles={roles} />);
  await stream.allReady;
  return new Response(stream).text();
}

describe("App routing", () => {
  it("renders an accessible loading state while a route chunk resolves", () => {
    route = "/market-overview";
    const html = renderToStaticMarkup(<App roles={["platform_admin"]} />);
    expect(html).toContain('role="status"');
    expect(html).toContain("正在加载终端模块");
  });

  it.each(terminalRoutes.filter((contract) => contract.status === "planned"))(
    "renders $id at its stable route as an explicit placeholder",
    async (contract) => {
      route = contract.href;
      const html = await renderApp(["platform_admin"]);
      expect(html).toContain("此功能不在 1.0 范围");
      expect(html).toContain(`data-route-placeholder="${contract.id}"`);
      expect(html).not.toContain(`DEFERRED_FEATURE:${contract.id}`);
    },
  );

  it("supports dynamic instrument deep links", async () => {
    route = "/instruments/600519.SH";
    const html = await renderApp();
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
    const navs = [...html.matchAll(/<nav aria-label="(?:桌面|移动端)主导航"[\s\S]*?<\/nav>/g)];
    expect(navs).toHaveLength(2);
    for (const nav of navs) {
      const markup = nav[0];
      expect(markup).toContain('href="/market-overview"');
      expect(markup).toContain('href="/instruments"');
      expect(markup).toContain('href="/watchlists"');
      expect(markup).not.toContain('href="/paper"');
      expect(markup).not.toContain('href="/ranking"');
    }
  });

  it("shows only the release routes on Home and uses daily research wording", async () => {
    route = "/";
    const html = await renderApp(["platform_admin"]);
    expect(html).toContain("查看沪深日线行情与自选提醒");
    expect(html).toContain("/market-overview");
    expect(html).toContain("/instruments");
    expect(html).toContain("/watchlists");
    expect(html).toContain('href="/"');
    expect(html).not.toContain("/paper");
    expect(html).not.toContain("/ranking");
    expect(html).not.toContain("已就绪");
    expect(html).not.toContain("规划能力待接入");
    expect(html).not.toContain("模拟执行");
  });

  it("keeps unknown deep links on the navigable 404 page", () => {
    route = "/not-a-terminal-route";
    expect(renderToStaticMarkup(<App />)).toContain("404");
  });

  it("registers every route contract through the generated router", async () => {
    for (const contract of terminalRoutes) {
      route = contract.href.replace("600519.SH", "000001.SZ");
      expect(await renderApp(["platform_admin"])).not.toContain("页面不存在");
    }
  });

  it("preserves point-in-time and instrument filters across module navigation", () => {
    route = "/market-overview?asOf=2026-08-24T07%3A00%3A00.000Z&instrument=600519.SH";
    const html = renderToStaticMarkup(<App roles={["viewer"]} />);
    expect(html).toContain("上下文 1 标的");
    expect(html).toContain("/instruments?asOf=2026-08-24T07%3A00%3A00.000Z");
    expect(html).toContain("instrument=600519.SH");
  });
});
