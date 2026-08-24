import { NavLink, Outlet } from "react-router";
import { ErrorBoundary } from "./ErrorBoundary";

const navigation = [
  { to: "/", label: "首页" },
  { to: "/data-quality", label: "数据质量" },
  { to: "/market-regime", label: "情绪与轮动" },
  { to: "/event-workbench", label: "事件观势" },
];

export function Layout() {
  return (
    <ErrorBoundary>
      <div className="flex min-h-screen flex-col bg-background">
        <header className="border-b bg-card px-6 py-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">昆仑智策</h1>
              <span className="text-xs text-muted-foreground">Kunlun Alpha</span>
            </div>
            <nav aria-label="主导航" className="flex items-center gap-1">
              {navigation.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    [
                      "rounded-md px-3 py-2 text-sm transition-colors",
                      isActive
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    ].join(" ")
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
        </header>
        <main className="flex-1 p-4 sm:p-6">
          <Outlet />
        </main>
      </div>
    </ErrorBoundary>
  );
}
