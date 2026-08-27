import type {
  PaperTerminalCreateAccountCommand,
  PaperTerminalSimulationCommand,
  PaperTerminalWorkspace,
} from "@kunlun/shared-types";

export interface PaperEngineClient {
  workspace(): Promise<PaperTerminalWorkspace>;
  createAccount(command: PaperTerminalCreateAccountCommand): Promise<PaperTerminalWorkspace>;
  simulate(command: PaperTerminalSimulationCommand): Promise<PaperTerminalWorkspace>;
}

export class PaperEngineHttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "PaperEngineHttpError";
  }
}

export class HttpPaperEngineClient implements PaperEngineClient {
  constructor(
    private readonly baseUrl: string,
    private readonly timeoutMs: number,
  ) {}

  workspace(): Promise<PaperTerminalWorkspace> {
    return this.request("/v1/paper/workspace", { method: "GET" });
  }

  createAccount(command: PaperTerminalCreateAccountCommand): Promise<PaperTerminalWorkspace> {
    return this.request("/v1/paper/accounts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(command),
    });
  }

  simulate(command: PaperTerminalSimulationCommand): Promise<PaperTerminalWorkspace> {
    return this.request("/v1/paper/simulations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(command),
    });
  }

  private async request(path: string, init: RequestInit): Promise<PaperTerminalWorkspace> {
    let response: Response;
    try {
      response = await fetch(new URL(path, this.baseUrl), {
        ...init,
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (error) {
      throw new PaperEngineHttpError(
        error instanceof Error ? error.message : "quant-engine unavailable",
        503,
      );
    }
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { message?: unknown } | null;
      const detail =
        typeof payload?.message === "string" ? payload.message : `HTTP ${response.status}`;
      throw new PaperEngineHttpError(detail, response.status);
    }
    return (await response.json()) as PaperTerminalWorkspace;
  }
}
