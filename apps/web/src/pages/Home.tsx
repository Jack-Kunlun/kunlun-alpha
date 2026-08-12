import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { env } from "../env";

export function Home() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <CardTitle className="text-2xl">{env.TITLE}</CardTitle>
            <Badge variant="secondary">v0.0.0</Badge>
          </div>
          <CardDescription className="text-base">观势 · 知势 · 策势</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            A 股智能投研与量化平台。覆盖市场情绪、板块轮动、热点事件、
            席位分析、因子研究与量化回测的全链路投研工作台。
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Phase</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">0</p>
            <p className="text-xs text-muted-foreground">工程基础设施</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Node</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">P0-N07</p>
            <p className="text-xs text-muted-foreground">shadcn/ui 设计基线</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Nodes</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">98</p>
            <p className="text-xs text-muted-foreground">总计开发节点</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
