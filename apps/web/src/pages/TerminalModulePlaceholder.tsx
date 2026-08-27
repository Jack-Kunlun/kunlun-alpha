import { ArrowLeft, Construction } from "lucide-react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getTerminalRoute, type TerminalRouteId } from "@/app/route-contract";
import { useTerminalFilters } from "@/app/filter-context";

export function TerminalModulePlaceholder({ routeId }: { routeId: TerminalRouteId }) {
  const route = getTerminalRoute(routeId);
  const { hrefForRoute } = useTerminalFilters();
  return (
    <div className="mx-auto max-w-4xl py-8">
      <Card className="overflow-hidden border-dashed bg-card/90">
        <div className="h-1 bg-gradient-to-r from-amber-400 via-sky-500 to-emerald-500" />
        <CardHeader className="space-y-5 sm:p-8">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">规划能力</Badge>
            <Badge variant="secondary">路由已就绪</Badge>
          </div>
          <div className="flex items-start gap-4">
            <div className="mt-1 flex size-11 shrink-0 items-center justify-center rounded-2xl bg-muted">
              <Construction aria-hidden="true" className="size-5 text-muted-foreground" />
            </div>
            <div>
              <span className="sr-only">ROUTE_PLACEHOLDER:{route.id}</span>
              <CardTitle className="text-2xl sm:text-3xl">{route.label}</CardTitle>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                {route.description}
                。当前页面只保留稳定深链接；真实业务数据接入前不展示模拟行情或结论。
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="border-t bg-muted/30 px-6 py-5 sm:px-8">
          <Button asChild variant="ghost">
            <Link to={hrefForRoute("/")}>
              <ArrowLeft aria-hidden="true" />
              返回决策总览
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
