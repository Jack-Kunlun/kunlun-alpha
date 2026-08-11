import { Link } from "react-router";
import { Button } from "@/components/ui/button";

export function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <h2 className="text-6xl font-bold text-muted-foreground/30">404</h2>
      <p className="mt-4 text-muted-foreground">页面不存在</p>
      <Button asChild className="mt-6" variant="default">
        <Link to="/">返回首页</Link>
      </Button>
    </div>
  );
}
