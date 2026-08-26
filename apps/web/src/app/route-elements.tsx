import { RankingTerminalPage } from "../features/ranking/ranking-terminal-page";
import type { ReactNode } from "react";
import type { TerminalRouteId } from "./route-contract";
import { BacktestRegressionPage } from "../features/backtest/backtest-regression-page";
import { DataQualityPage } from "../features/data-quality/data-quality-page";
import { EventWorkbenchPage } from "../features/event-workbench/event-workbench-page";
import { MarketRegimePage } from "../features/market-regime/market-regime-page";
import { MarketOverviewPage } from "../features/market-overview/market-overview-page";
import { LimitPoolTerminalPage } from "../features/limit-pool/limit-pool-terminal-page";
import { RotationTerminalPage } from "../features/rotation/rotation-terminal-page";
import { SeatKolWorkbenchPage } from "../features/seat-kol/seat-kol-workbench-page";
import { Home } from "../pages/Home";
import { TerminalModulePlaceholder } from "../pages/TerminalModulePlaceholder";

export const terminalRouteElements: Readonly<Record<TerminalRouteId, ReactNode>> = {
  home: <Home />,
  "market-overview": <MarketOverviewPage />,
  "limit-pool": <LimitPoolTerminalPage />,
  rotation: <RotationTerminalPage />,
  ranking: <RankingTerminalPage />,
  instruments: <TerminalModulePlaceholder routeId="instruments" />,
  "instrument-detail": <TerminalModulePlaceholder routeId="instrument-detail" />,
  "precious-metals": <TerminalModulePlaceholder routeId="precious-metals" />,
  watchlists: <TerminalModulePlaceholder routeId="watchlists" />,
  paper: <TerminalModulePlaceholder routeId="paper" />,
  "market-regime": <MarketRegimePage />,
  "event-workbench": <EventWorkbenchPage />,
  "seat-kol": <SeatKolWorkbenchPage />,
  "backtest-regressions": <BacktestRegressionPage />,
  "data-quality": <DataQualityPage />,
};
