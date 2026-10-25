import type {
  PaperAllocationDecision,
  PaperRiskDecision,
  PaperReconciliationResult,
  PaperTerminalCreateAccountCommand,
  PaperTerminalSimulationCommand,
  PaperTerminalWorkspace,
} from "@kunlun/shared-types";
import { parsePaperWorkspaceResponse } from "./paper-workspace-response";
import { parsePaperPreviewResponse } from "./paper-preview-response";
import { parsePaperRiskPreviewResponse } from "./paper-risk-response";
import { parsePaperReconciliationResponse } from "./paper-reconciliation-response";
import { parsePaperBuyResponse } from "./paper-buy-response";

export interface PaperEngineClient {
  reconciliation(): Promise<PaperReconciliationResult>;
  buyAllocation(allocation: PaperAllocationDecision): Promise<PaperTerminalWorkspace>;
  riskPreview(allocation: PaperAllocationDecision): Promise<PaperRiskDecision>;
  preview(command: PaperTerminalSimulationCommand): Promise<PaperAllocationDecision>;
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
    private readonly controlledBuyEnabled = false,
  ) {}

  async reconciliation(): Promise<PaperReconciliationResult> {
    const value = await this.requestRaw("/v1/paper/reconciliation", { method: "GET" });
    try {
      return parsePaperReconciliationResponse(value);
    } catch {
      throw new PaperEngineHttpError("quant-engine returned an invalid paper reconciliation", 502);
    }
  }

  async riskPreview(allocation: PaperAllocationDecision): Promise<PaperRiskDecision> {
    const value = await this.requestRaw("/v1/paper/risk-previews", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(allocation),
    });
    try {
      return parsePaperRiskPreviewResponse(value, allocation, this.controlledBuyEnabled);
    } catch {
      throw new PaperEngineHttpError("quant-engine returned an invalid paper risk preview", 502);
    }
  }

  async buyAllocation(allocation: PaperAllocationDecision): Promise<PaperTerminalWorkspace> {
    const value = await this.requestRaw("/v1/paper/buy-simulations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(allocation),
    });
    try {
      return parsePaperBuyResponse(value, allocation);
    } catch {
      throw new PaperEngineHttpError("quant-engine returned an invalid controlled paper buy", 502);
    }
  }

  async preview(command: PaperTerminalSimulationCommand): Promise<PaperAllocationDecision> {
    const value = await this.requestRaw("/v1/paper/previews", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(command),
    });
    try {
      return parsePaperPreviewResponse(value, command);
    } catch {
      throw new PaperEngineHttpError("quant-engine returned an invalid paper preview", 502);
    }
  }

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
    const payload = await this.requestRaw(path, init);
    try {
      return parsePaperWorkspaceResponse(payload);
    } catch {
      throw new PaperEngineHttpError("quant-engine returned an invalid paper workspace", 502);
    }
  }

  private async requestRaw(path: string, init: RequestInit): Promise<unknown> {
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
        response.status === 409 &&
        ["/v1/paper/risk-previews", "/v1/paper/buy-simulations"].includes(path)
          ? "试算基准已变化，请重新试算"
          : response.status === 409
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
    return payload;
  }
}
