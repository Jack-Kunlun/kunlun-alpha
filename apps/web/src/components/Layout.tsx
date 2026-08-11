import { Outlet } from "react-router";
import { ErrorBoundary } from "./ErrorBoundary";

export function Layout() {
  return (
    <ErrorBoundary>
      <div className="flex min-h-screen flex-col bg-background">
        <header className="border-b bg-card px-6 py-4">
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-semibold tracking-tight">昆仑智策</h1>
            <span className="text-xs text-muted-foreground">Kunlun Alpha</span>
          </div>
        </header>
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </ErrorBoundary>
  );
}
