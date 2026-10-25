import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { currentInstrumentDailyHref } from "@/features/instrument/instrument-daily-link";

/** Research navigation only: the target's daily prices never update a simulation snapshot. */
export function PaperInstrumentLink({ instrumentId }: { instrumentId: string }) {
  const href = currentInstrumentDailyHref(instrumentId);
  if (href === null) return <span className="font-mono">{instrumentId}</span>;
  return (
    <Button
      asChild
      variant="link"
      size="sm"
      className="h-auto min-h-6 cursor-pointer rounded-sm px-0 py-0 font-mono"
    >
      <Link
        to={href}
        aria-label={`查看 ${instrumentId} 当前已入库日线`}
        title="查看当前已入库日线，不重算模拟价格或账本"
      >
        {instrumentId}
      </Link>
    </Button>
  );
}
