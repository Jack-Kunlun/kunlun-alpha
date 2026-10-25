import {
  BadRequestException,
  ConflictException,
  ForbiddenException,
  Inject,
  Injectable,
  ServiceUnavailableException,
} from "@nestjs/common";
import type {
  PaperAllocationDecision,
  PaperRiskDecision,
  PaperTerminalCreateAccountCommand,
  PaperTerminalSimulationCommand,
  PaperTerminalWorkspace,
} from "@kunlun/shared-types";
import { PaperEngineHttpError, type PaperEngineClient } from "./paper-engine.client";
import {
  PAPER_ENGINE_CLIENT,
  PAPER_TERMINAL_ACCOUNT_ONLY,
  PAPER_CONTROLLED_BUY_ENABLED,
} from "./paper-terminal.tokens";
import {
  PaperTerminalValidationError,
  parseCreateAccount,
  parseSimulation,
} from "./paper-terminal.validation";
import { parsePaperRiskPreviewRequest } from "./paper-risk-response";

@Injectable()
export class PaperTerminalService {
  constructor(
    @Inject(PAPER_ENGINE_CLIENT) private readonly client: PaperEngineClient,
    @Inject(PAPER_TERMINAL_ACCOUNT_ONLY) private readonly accountOnly = false,
    @Inject(PAPER_CONTROLLED_BUY_ENABLED) private readonly controlledBuyEnabled = false,
  ) {}

  async workspace(): Promise<PaperTerminalWorkspace> {
    try {
      return await this.client.workspace();
    } catch {
      return unavailableWorkspace();
    }
  }

  async createAccount(body: unknown): Promise<PaperTerminalWorkspace> {
    const command = this.parseCreate(body);
    return this.execute(() => this.client.createAccount(command));
  }

  async simulate(body: unknown): Promise<PaperTerminalWorkspace> {
    if (this.accountOnly) {
      throw new ForbiddenException("当前版本只开放模拟账户与只读账本，模拟成交尚未开放");
    }
    const command = this.parseSimulation(body);
    return this.execute(() => this.client.simulate(command));
  }

  async preview(body: unknown) {
    const command = this.parseSimulation(body);
    return this.execute(() => this.client.preview(command));
  }

  async riskPreview(body: unknown): Promise<PaperRiskDecision> {
    let allocation: PaperAllocationDecision;
    try {
      allocation = parsePaperRiskPreviewRequest(body);
    } catch {
      throw new BadRequestException("请提供一份有效的仓位试算结果");
    }
    return this.execute(() => this.client.riskPreview(allocation));
  }

  async buyAllocation(body: unknown): Promise<PaperTerminalWorkspace> {
    if (!this.controlledBuyEnabled) throw new ForbiddenException("受控模拟买入尚未启用");
    let allocation: PaperAllocationDecision;
    try {
      allocation = parsePaperRiskPreviewRequest(body);
    } catch {
      throw new BadRequestException("请提供一份有效的仓位试算结果");
    }
    if (allocation.intents[0]?.side !== "BUY")
      throw new BadRequestException("当前仅支持受控模拟买入");
    return this.execute(() => this.client.buyAllocation(allocation));
  }

  private parseCreate(body: unknown): PaperTerminalCreateAccountCommand {
    try {
      return parseCreateAccount(body);
    } catch (error) {
      if (error instanceof PaperTerminalValidationError)
        throw new BadRequestException(error.message);
      throw error;
    }
  }

  private parseSimulation(body: unknown): PaperTerminalSimulationCommand {
    try {
      return parseSimulation(body);
    } catch (error) {
      if (error instanceof PaperTerminalValidationError)
        throw new BadRequestException(error.message);
      throw error;
    }
  }

  private async execute<T>(operation: () => Promise<T>): Promise<T> {
    try {
      return await operation();
    } catch (error) {
      if (error instanceof PaperEngineHttpError && error.status === 409) {
        throw new ConflictException(error.message);
      }
      if (error instanceof PaperEngineHttpError && error.status === 422) {
        throw new BadRequestException(error.message);
      }
      throw new ServiceUnavailableException("模拟引擎暂不可用");
    }
  }
}

function unavailableWorkspace(): PaperTerminalWorkspace {
  return {
    schemaVersion: "paper-terminal-workspace-v1",
    status: "UNAVAILABLE",
    dataMeaning: "SIMULATION_ONLY_NO_BROKER_PATH",
    executionCapability: "PAPER_ONLY",
    persistenceMode: "VOLATILE_IN_MEMORY",
    generatedAt: new Date().toISOString(),
    limitations: [
      "模拟引擎当前不可达，请检查 quant-engine 健康状态。",
      "当前系统不连接真实账户或券商，也不会生成真实订单。",
    ],
    account: null,
    latestAllocation: null,
    orders: [],
    latestRisk: null,
    reconciliation: null,
    audit: {
      accountEventCount: 0,
      executionEventCount: 0,
      orderAuditCount: 0,
      alertCount: 0,
      accountDigest: null,
      executionDigest: null,
      lastClientRequestId: null,
    },
  };
}
