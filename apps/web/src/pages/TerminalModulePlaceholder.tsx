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
            <Badge variant="outline">后续版本</Badge>
          </div>
          <div className="flex items-start gap-4">
            <div className="mt-1 flex size-11 shrink-0 items-center justify-center rounded-2xl bg-muted">
              <Construction aria-hidden="true" className="size-5 text-muted-foreground" />
            </div>
            <div>
              <span aria-hidden="true" className="sr-only" data-route-placeholder={route.id}>
                ROUTE_PLACEHOLDER:{route.id}
              </span>
              <CardTitle className="text-2xl sm:text-3xl">{route.label}</CardTitle>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                此功能不在 1.0 范围。当前保留原有访问路径，后续版本再开放。
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="border-t bg-muted/30 px-6 py-5 sm:px-8">
          <Button asChild variant="ghost">
            <Link to={hrefForRoute("/")}>
              <ArrowLeft aria-hidden="true" />
              返回首页
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
