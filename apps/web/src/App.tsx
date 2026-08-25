import { BrowserRouter, Routes, Route } from "react-router";
import { Toaster } from "@/components/ui/sonner";
import { Layout } from "./components/Layout";
import { Home } from "./pages/Home";
import { NotFound } from "./pages/NotFound";
import { DataQualityPage } from "./features/data-quality/data-quality-page";
import { MarketRegimePage } from "./features/market-regime/market-regime-page";
import { EventWorkbenchPage } from "./features/event-workbench/event-workbench-page";
import { SeatKolWorkbenchPage } from "./features/seat-kol/seat-kol-workbench-page";
import { BacktestRegressionPage } from "./features/backtest/backtest-regression-page";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="data-quality" element={<DataQualityPage />} />
          <Route path="market-regime" element={<MarketRegimePage />} />
          <Route path="event-workbench" element={<EventWorkbenchPage />} />
          <Route path="seat-kol" element={<SeatKolWorkbenchPage />} />
          <Route path="backtest/regressions" element={<BacktestRegressionPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
      <Toaster />
    </BrowserRouter>
  );
}
