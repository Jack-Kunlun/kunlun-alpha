import { LockKeyhole } from "lucide-react";
import { Link, useLocation } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTerminalFilters } from "@/app/filter-context";

export function Forbidden() {
  const location = useLocation();
  const { hrefForRoute } = useTerminalFilters();
  return (
    <div className="mx-auto flex min-h-[55vh] max-w-2xl items-center justify-center py-12">
      <Card className="w-full border-amber-500/25 bg-card/95 shadow-xl shadow-slate-950/5">
        <CardHeader className="space-y-4">
          <div className="flex size-12 items-center justify-center rounded-2xl bg-amber-500/10 text-amber-600 dark:text-amber-400">
            <LockKeyhole aria-hidden="true" className="size-6" />
          </div>
          <div>
            <span className="sr-only">FORBIDDEN_ROUTE</span>
            <p className="text-xs font-semibold tracking-[0.18em] text-muted-foreground uppercase">
              Access boundary
            </p>
            <CardTitle className="mt-2 text-2xl">无权访问此终端模块</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <p className="text-sm leading-6 text-muted-foreground">
            当前身份没有访问 <code className="rounded bg-muted px-1.5 py-0.5">{location.pathname}</code>
            的权限。前端限制只用于清晰反馈，服务端权限仍是最终边界。
          </p>
          <Button asChild>
            <Link to={hrefForRoute("/")}>返回决策总览</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
