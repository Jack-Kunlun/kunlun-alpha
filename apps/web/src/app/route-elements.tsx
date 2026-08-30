import { lazy, Suspense, type ComponentType, type ReactNode } from "react";
import type { TerminalRouteId } from "./route-contract";

const Home = lazy(async () => ({ default: (await import("../pages/Home")).Home }));
const MarketOverviewPage = lazy(async () => ({
  default: (await import("../features/market-overview/market-overview-page")).MarketOverviewPage,
}));
const LimitPoolTerminalPage = lazy(async () => ({
  default: (await import("../features/limit-pool/limit-pool-terminal-page")).LimitPoolTerminalPage,
}));
const RotationTerminalPage = lazy(async () => ({
  default: (await import("../features/rotation/rotation-terminal-page")).RotationTerminalPage,
}));
const RankingTerminalPage = lazy(async () => ({
  default: (await import("../features/ranking/ranking-terminal-page")).RankingTerminalPage,
}));
const InstrumentDirectoryPage = lazy(async () => ({
  default: (await import("../features/instrument/instrument-intelligence-page"))
    .InstrumentDirectoryPage,
}));
const InstrumentIntelligencePage = lazy(async () => ({
  default: (await import("../features/instrument/instrument-intelligence-page"))
    .InstrumentIntelligencePage,
}));
const PreciousMetalsTerminalPage = lazy(async () => ({
  default: (await import("../features/precious-metals/precious-metals-terminal-page"))
    .PreciousMetalsTerminalPage,
}));
const AlertsPage = lazy(async () => ({
  default: (await import("../features/alerts/alerts-page")).AlertsPage,
}));
const PaperTerminalPage = lazy(async () => ({
  default: (await import("../features/paper/paper-terminal-page")).PaperTerminalPage,
}));
const MarketRegimePage = lazy(async () => ({
  default: (await import("../features/market-regime/market-regime-page")).MarketRegimePage,
}));
const EventWorkbenchPage = lazy(async () => ({
  default: (await import("../features/event-workbench/event-workbench-page")).EventWorkbenchPage,
}));
const SeatKolWorkbenchPage = lazy(async () => ({
  default: (await import("../features/seat-kol/seat-kol-workbench-page")).SeatKolWorkbenchPage,
}));
const BacktestRegressionPage = lazy(async () => ({
  default: (await import("../features/backtest/backtest-regression-page")).BacktestRegressionPage,
}));
const DataQualityPage = lazy(async () => ({
  default: (await import("../features/data-quality/data-quality-page")).DataQualityPage,
}));

function RouteLoading() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-2xl border bg-card p-6 text-sm text-muted-foreground shadow-sm"
    >
      <div className="mb-3 h-2 w-24 rounded-full bg-muted motion-safe:animate-pulse" />
      正在加载终端模块…
    </div>
  );
}

function lazyRoute(Page: ComponentType): ReactNode {
  return (
    <Suspense fallback={<RouteLoading />}>
      <Page />
    </Suspense>
  );
}

export const terminalRouteElements: Readonly<Record<TerminalRouteId, ReactNode>> = {
  home: lazyRoute(Home),
  "market-overview": lazyRoute(MarketOverviewPage),
  "limit-pool": lazyRoute(LimitPoolTerminalPage),
  rotation: lazyRoute(RotationTerminalPage),
  ranking: lazyRoute(RankingTerminalPage),
  instruments: lazyRoute(InstrumentDirectoryPage),
  "instrument-detail": lazyRoute(InstrumentIntelligencePage),
  "precious-metals": lazyRoute(PreciousMetalsTerminalPage),
  watchlists: lazyRoute(AlertsPage),
  paper: lazyRoute(PaperTerminalPage),
  "market-regime": lazyRoute(MarketRegimePage),
  "event-workbench": lazyRoute(EventWorkbenchPage),
  "seat-kol": lazyRoute(SeatKolWorkbenchPage),
  "backtest-regressions": lazyRoute(BacktestRegressionPage),
  "data-quality": lazyRoute(DataQualityPage),
};
