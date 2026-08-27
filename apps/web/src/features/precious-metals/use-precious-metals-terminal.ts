import type { PreciousMetalsTerminalSnapshot } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery } from "@/lib/use-api-query";

export const PRECIOUS_METALS_TERMINAL_PATH = "/v1/precious-metals/terminal";

export function preciousMetalsTerminalQuery(asOf: string | null): Record<string, string> {
  return asOf === null ? { mode: "CURRENT" } : { mode: "HISTORICAL", asOf };
}

export function usePreciousMetalsTerminal(asOf: string | null) {
  return useApiObjectQuery(
    () =>
      apiClient.get<PreciousMetalsTerminalSnapshot>(
        PRECIOUS_METALS_TERMINAL_PATH,
        preciousMetalsTerminalQuery(asOf),
      ),
    [asOf],
    true,
    asOf === null ? 60_000 : 0,
  );
}
