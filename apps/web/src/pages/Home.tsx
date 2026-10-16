import { ArrowUpRight, Compass, ShieldCheck } from "lucide-react";
import { Link } from "react-router";
import { useTerminalRoles } from "@/app/access-control";
import { terminalNavigationGroups, visibleTerminalRoutes } from "@/app/route-contract";
import { useTerminalFilters } from "@/app/filter-context";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function Home() {
  const { hrefForRoute } = useTerminalFilters();
  const roles = useTerminalRoles();
  const productRoutes = visibleTerminalRoutes(roles);
  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-3xl border bg-slate-950 px-6 py-8 text-white shadow-2xl shadow-slate-950/10 sm:px-10 sm:py-12">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_85%_15%,rgba(56,189,248,0.2),transparent_28%),radial-gradient(circle_at_15%_85%,rgba(251,191,36,0.18),transparent_30%)]" />
        <div className="relative max-w-3xl">
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <Badge className="border-white/15 bg-white/10 text-white" variant="outline">
              日线研究终端
            </Badge>
            <Badge className="border-amber-300/30 bg-amber-300/10 text-amber-200" variant="outline">
              历史日线 · 站内提醒
            </Badge>
          </div>
          <div className="flex items-start gap-4">
            <Compass aria-hidden="true" className="mt-1 hidden size-9 text-amber-300 sm:block" />
            <div>
              <h2 className="text-3xl font-semibold tracking-tight sm:text-5xl">
                查看沪深日线行情与自选提醒
              </h2>
              <p className="mt-5 max-w-2xl text-sm leading-7 text-slate-300 sm:text-base">
                查询已接入标的的历史日线，查看行情来源和日期，并管理价格、涨跌幅站内提醒。数据以最近完成的日线采集为准。
              </p>
            </div>
          </div>
          <div className="mt-8 flex items-center gap-2 text-xs text-emerald-300">
            <ShieldCheck aria-hidden="true" className="size-4" />
            <span>页面展示历史行情，不代表实时行情</span>
          </div>
        </div>
      </section>

      <section aria-labelledby="terminal-map-title">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-semibold tracking-[0.16em] text-muted-foreground uppercase">
              Terminal map
            </p>
            <h2 id="terminal-map-title" className="mt-1 text-2xl font-semibold tracking-tight">
              1.0 可用入口
            </h2>
          </div>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          {terminalNavigationGroups.map((group) => {
            const routes = productRoutes.filter((route) => route.group === group.id);
            if (routes.length === 0) return null;
            return (
              <Card
                key={group.id}
                className="group overflow-hidden bg-card/90 transition-shadow hover:shadow-lg"
              >
                <CardHeader>
                  <CardTitle className="text-lg">{group.label}</CardTitle>
                  <CardDescription>{group.description}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  {routes.slice(0, 5).map((route) => (
                    <Link
                      key={route.id}
                      to={hrefForRoute(route.href)}
                      className="flex items-center justify-between gap-3 rounded-xl border border-transparent px-3 py-2 text-sm transition-colors hover:border-border hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="truncate">{route.label}</span>
                      <span className="flex shrink-0 items-center gap-2">
                        {route.status === "planned" && (
                          <span className="text-[10px] text-muted-foreground">规划</span>
                        )}
                        <ArrowUpRight
                          aria-hidden="true"
                          className="size-3.5 text-muted-foreground"
                        />
                      </span>
                    </Link>
                  ))}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>
    </div>
  );
}
