import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import type * as ReactRouter from "react-router";
import { describe, expect, it, vi } from "vitest";

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
vi.mock("./components/ui/sonner", () => ({ Toaster: () => null }));

import { App } from "./App";

describe("App routing", () => {
  it("serves the data-quality page", () => {
    route = "/data-quality";
    expect(renderToStaticMarkup(<App />)).toContain("DATA_QUALITY_PAGE_MARKER");
  });

  it("serves the persisted market-regime replay page", () => {
    route = "/market-regime";
    expect(renderToStaticMarkup(<App />)).toContain("MARKET_REGIME_PAGE_MARKER");
  });

  it("serves the Phase 3 event workbench", () => {
    route = "/event-workbench";
    expect(renderToStaticMarkup(<App />)).toContain("EVENT_WORKBENCH_PAGE_MARKER");
  });

  it("serves the Phase 4 Seat and KOL workbench", () => {
    route = "/seat-kol";
    expect(renderToStaticMarkup(<App />)).toContain("SEAT_KOL_WORKBENCH_MARKER");
  });
});
