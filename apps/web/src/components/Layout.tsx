import {
  Activity,
  Bell,
  ChartNoAxesCombined,
  CircleGauge,
  Database,
  FlaskConical,
  Flame,
  Gem,
  House,
  ListFilter,
  LogOut,
  Menu,
  Newspaper,
  Orbit,
  Search,
  ShieldCheck,
  UsersRound,
  WalletCards,
  type LucideIcon,
} from "lucide-react";
import { matchPath, NavLink, Outlet, useLocation } from "react-router";
import { useTerminalRoles } from "@/app/access-control";
import { useTerminalFilters } from "@/app/filter-context";
import {
  terminalNavigationGroups,
  terminalRoutes,
  visibleTerminalRoutes,
  type TerminalRouteContract,
  type TerminalRouteId,
} from "@/app/route-contract";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useOptionalAuth } from "@/features/auth/auth-context";
import { ErrorBoundary } from "./ErrorBoundary";

const routeIcons: Record<TerminalRouteId, LucideIcon> = {
  home: House,
  "market-overview": Activity,
  "limit-pool": Flame,
  rotation: Orbit,
  ranking: ListFilter,
  instruments: Search,
  "instrument-detail": Search,
  "precious-metals": Gem,
  watchlists: Bell,
  paper: WalletCards,
  "market-regime": ChartNoAxesCombined,
  "event-workbench": Newspaper,
  "seat-kol": UsersRound,
  "backtest-regressions": FlaskConical,
  "data-quality": Database,
};

function RouteLink({ route, mobile = false }: { route: TerminalRouteContract; mobile?: boolean }) {
  const Icon = routeIcons[route.id];
  const { hrefForRoute } = useTerminalFilters();
  return (
    <NavLink
      to={hrefForRoute(route.href)}
      end={route.path === "/"}
      className={({ isActive }) =>
        [
          "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-amber-400/80",
          isActive
            ? mobile
              ? "bg-slate-900 text-white"
              : "bg-white/10 text-white shadow-inner shadow-white/5"
            : mobile
              ? "text-slate-600 hover:bg-slate-100 hover:text-slate-950"
              : "text-slate-300 hover:bg-white/7 hover:text-white",
        ].join(" ")
      }
    >
      <Icon aria-hidden="true" className="size-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate">{route.label}</span>
      {route.status === "planned" && (
        <span className="rounded-full border border-current/20 px-1.5 py-0.5 text-[10px] opacity-70">
          规划
        </span>
      )}
    </NavLink>
  );
}

function Navigation({ mobile = false }: { mobile?: boolean }) {
  const roles = useTerminalRoles();
  const routes = visibleTerminalRoutes(roles);
  return (
    <nav aria-label={mobile ? "移动端主导航" : "桌面主导航"} className="space-y-6">
      {terminalNavigationGroups.map((group) => {
        const groupRoutes = routes.filter((route) => route.group === group.id);
        if (groupRoutes.length === 0) return null;
        return (
          <section key={group.id} aria-labelledby={`${mobile ? "mobile" : "desktop"}-${group.id}`}>
            <div className="mb-2 px-3">
              <h2
                id={`${mobile ? "mobile" : "desktop"}-${group.id}`}
                className={
                  mobile
                    ? "text-xs font-semibold tracking-[0.15em] text-slate-500 uppercase"
                    : "text-[11px] font-semibold tracking-[0.18em] text-slate-500 uppercase"
                }
              >
                {group.label}
              </h2>
            </div>
            <div className="space-y-1">
              {groupRoutes.map((route) => (
                <RouteLink key={route.id} route={route} mobile={mobile} />
              ))}
            </div>
          </section>
        );
      })}
    </nav>
  );
}

export function Layout() {
  const location = useLocation();
  const { value: filters, rejected } = useTerminalFilters();
  const currentRoute = terminalRoutes.find((route) =>
    matchPath({ path: route.path, end: true }, location.pathname),
  );
  const auth = useOptionalAuth();
  return (
    <ErrorBoundary>
      <div className="terminal-canvas min-h-screen bg-background lg:grid lg:grid-cols-[17rem_minmax(0,1fr)]">
        <a
          href="#terminal-main"
          className="fixed top-2 left-2 z-50 -translate-y-16 rounded-md bg-amber-400 px-3 py-2 text-sm font-semibold text-slate-950 transition-transform focus:translate-y-0"
        >
          跳到主内容
        </a>

        <aside className="hidden min-h-screen border-r border-white/8 bg-slate-950 text-white lg:sticky lg:top-0 lg:block lg:h-screen">
          <div className="flex h-full flex-col">
            <div className="border-b border-white/8 px-6 py-6">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-2xl bg-amber-400 text-slate-950 shadow-lg shadow-amber-400/15">
                  <CircleGauge aria-hidden="true" className="size-5" />
                </div>
                <div>
                  <p className="font-semibold tracking-wide">昆仑智策</p>
                  <p className="text-xs text-slate-500">观势 · 知势 · 策势</p>
                </div>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-6">
              <Navigation />
            </div>
            <div className="border-t border-white/8 px-5 py-4">
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <ShieldCheck aria-hidden="true" className="size-4 text-emerald-400" />
                <span>研究与模拟环境</span>
              </div>
              <p className="mt-1 text-[11px] text-slate-600">无真实账户与下单路径</p>
            </div>
          </div>
        </aside>

        <div className="min-w-0">
          <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur-xl">
            <div className="flex min-h-16 items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground uppercase">
                  {currentRoute?.group === "research"
                    ? "Research & audit"
                    : currentRoute?.group === "workspace"
                      ? "Action workspace"
                      : "Decision terminal"}
                </p>
                <h1 className="truncate text-lg font-semibold tracking-tight">
                  {currentRoute?.label ?? "未知路径"}
                </h1>
              </div>
              <div className="flex items-center gap-2">
                {auth?.status === "authenticated" && auth.message !== null && (
                  <span role="alert" className="hidden text-xs text-red-600 sm:inline">
                    {auth.message}
                  </span>
                )}
                {auth?.session !== null && auth?.session !== undefined && (
                  <div className="hidden items-center gap-2 md:flex">
                    <span className="max-w-40 truncate text-xs text-muted-foreground">
                      {auth.session.user.displayName}
                    </span>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={auth.pending}
                      onClick={() => void auth.logout()}
                    >
                      <LogOut aria-hidden="true" className="size-4" />
                      退出
                    </Button>
                  </div>
                )}
                {(filters.asOf !== null || filters.instrumentIds.length > 0) && (
                  <Badge className="hidden md:inline-flex" variant="secondary">
                    上下文 {filters.instrumentIds.length} 标的
                  </Badge>
                )}
                {rejected.length > 0 && (
                  <Badge className="hidden md:inline-flex" variant="destructive">
                    筛选参数已拒绝
                  </Badge>
                )}
                <Badge className="hidden sm:inline-flex" variant="outline">
                  模拟环境
                </Badge>
                <details className="relative lg:hidden">
                  <summary className="flex size-10 cursor-pointer list-none items-center justify-center rounded-xl border bg-card text-foreground shadow-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                    <Menu aria-hidden="true" className="size-5" />
                    <span className="sr-only">打开主导航</span>
                  </summary>
                  <div className="absolute top-12 right-0 max-h-[calc(100vh-5rem)] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border bg-card p-4 shadow-2xl">
                    <div className="mb-5 border-b pb-4">
                      <p className="font-semibold">昆仑智策</p>
                      <p className="text-xs text-muted-foreground">观势 · 知势 · 策势</p>
                    </div>
                    <Navigation mobile />
                  </div>
                </details>
              </div>
            </div>
          </header>
          <main id="terminal-main" tabIndex={-1} className="p-4 outline-none sm:p-6 lg:p-8">
            <div className="mx-auto max-w-[100rem] rounded-2xl border bg-background/80 p-4 shadow-sm backdrop-blur-sm sm:p-6">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </ErrorBoundary>
  );
}
