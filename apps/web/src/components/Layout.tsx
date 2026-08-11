import { Outlet } from "react-router";
import { ErrorBoundary } from "./ErrorBoundary";

export function Layout() {
  return (
    <ErrorBoundary>
      <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
        <header
          style={{
            padding: "16px 24px",
            borderBottom: "1px solid #e0e0e0",
            background: "#fff",
          }}
        >
          <h1 style={{ fontSize: 20, fontWeight: 600 }}>昆仑智策</h1>
        </header>
        <main style={{ flex: 1, padding: 24 }}>
          <Outlet />
        </main>
      </div>
    </ErrorBoundary>
  );
}
