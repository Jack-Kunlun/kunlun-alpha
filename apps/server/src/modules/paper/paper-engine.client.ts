import type {
  PaperTerminalCreateAccountCommand,
  PaperTerminalSimulationCommand,
  PaperTerminalWorkspace,
} from "@kunlun/shared-types";
import { parsePaperWorkspaceResponse } from "./paper-workspace-response";

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
      await response.body?.cancel().catch(() => undefined);
      const detail =
        response.status === 409
          ? "模拟账户已存在或请求内容冲突，请刷新账本核对"
          : response.status === 422
            ? "模拟账户请求未通过校验，请检查输入"
            : "模拟引擎暂不可用";
      throw new PaperEngineHttpError(detail, response.status);
    }
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new PaperEngineHttpError("quant-engine returned an invalid paper workspace", 502);
    }
    try {
      return parsePaperWorkspaceResponse(payload);
    } catch {
      throw new PaperEngineHttpError("quant-engine returned an invalid paper workspace", 502);
    }
  }
}
