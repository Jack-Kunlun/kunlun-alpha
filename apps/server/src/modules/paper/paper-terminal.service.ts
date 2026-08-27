import {
  BadRequestException,
  ConflictException,
  Inject,
  Injectable,
  ServiceUnavailableException,
} from "@nestjs/common";
import type {
  PaperTerminalCreateAccountCommand,
  PaperTerminalSimulationCommand,
  PaperTerminalWorkspace,
} from "@kunlun/shared-types";
import { PaperEngineHttpError, type PaperEngineClient } from "./paper-engine.client";
import { PAPER_ENGINE_CLIENT } from "./paper-terminal.tokens";
import {
  PaperTerminalValidationError,
  parseCreateAccount,
  parseSimulation,
} from "./paper-terminal.validation";

@Injectable()
export class PaperTerminalService {
  constructor(@Inject(PAPER_ENGINE_CLIENT) private readonly client: PaperEngineClient) {}

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
    const command = this.parseSimulation(body);
    return this.execute(() => this.client.simulate(command));
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

  private async execute(operation: () => Promise<PaperTerminalWorkspace>) {
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
