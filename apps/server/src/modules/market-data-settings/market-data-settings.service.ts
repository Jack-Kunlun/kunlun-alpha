import {
  BadRequestException,
  ConflictException,
  ForbiddenException,
  Inject,
  Injectable,
  Optional,
  ServiceUnavailableException,
} from "@nestjs/common";
import type {
  MarketDataProvider,
  MarketDataSettingsResponse,
  MarketDataSettingsUpdateRequest,
  MarketDataTokenAction,
  MarketDataWorkerSettingsResponse,
} from "@kunlun/shared-types";
import {
  decryptToken,
  encryptToken,
  envelopeConfigured,
  validateToken,
} from "./market-data-settings.crypto";
import { MarketDataSettingsConflictError } from "./market-data-settings.repository";
import {
  MARKET_DATA_SETTINGS_KEY_PROVIDER,
  MARKET_DATA_SETTINGS_REPOSITORY,
} from "./market-data-settings.tokens";
import {
  type MarketDataSettingsRepository,
  type MarketDataSettingsKeyProvider,
  type PersistedMarketDataSettings,
} from "./market-data-settings.types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PROVIDERS = new Set<MarketDataProvider>(["akshare", "tushare"]);
const TOKEN_ACTIONS = new Set<MarketDataTokenAction>(["KEEP", "REPLACE", "CLEAR"]);

@Injectable()
export class MarketDataSettingsService {
  constructor(
    @Inject(MARKET_DATA_SETTINGS_REPOSITORY)
    private readonly repository: MarketDataSettingsRepository,
    @Inject(MARKET_DATA_SETTINGS_KEY_PROVIDER)
    private readonly keyProvider: MarketDataSettingsKeyProvider,
    @Optional()
    private readonly clock: () => Date = () => new Date(),
  ) {}

  async getBrowserSettings(
    userId: string,
    roles: readonly string[],
  ): Promise<MarketDataSettingsResponse> {
    this.assertAdministrator(userId, roles);
    try {
      this.keyProvider.getKey();
      const persisted = await this.repository.get();
      return toBrowserResponse(persisted);
    } catch {
      throw new ServiceUnavailableException("行情源配置暂时不可用");
    }
  }

  async updateBrowserSettings(
    userId: string,
    roles: readonly string[],
    input: unknown,
  ): Promise<MarketDataSettingsResponse> {
    this.assertAdministrator(userId, roles);
    const request = parseUpdateRequest(input);
    try {
      this.keyProvider.getKey();
    } catch {
      throw new ServiceUnavailableException("行情源配置暂时不可用");
    }
    let current: PersistedMarketDataSettings | null;
    try {
      current = await this.repository.get();
    } catch {
      throw new ServiceUnavailableException("行情源配置暂时不可用");
    }
    const currentRevision = current?.revision ?? 0;
    if (request.expectedRevision !== currentRevision) {
      throw new ConflictException("行情源配置已被其他操作更新");
    }
    const tokenEnvelope = this.resolveTokenEnvelope(request, current);
    const updatedAt = this.now();
    try {
      const updated = await this.repository.compareAndSet({
        expectedRevision: request.expectedRevision,
        provider: request.provider,
        tokenEnvelope,
        tokenAction: request.tokenAction,
        actorId: userId,
        updatedAt,
      });
      return toBrowserResponse(updated);
    } catch (error) {
      if (error instanceof MarketDataSettingsConflictError) {
        throw new ConflictException("行情源配置已被其他操作更新");
      }
      throw new ServiceUnavailableException("行情源配置暂时不可用");
    }
  }

  async getWorkerSettings(): Promise<MarketDataWorkerSettingsResponse> {
    try {
      const key = this.keyProvider.getKey();
      const persisted = await this.repository.get();
      const effective = persisted ?? defaultSettings();
      let token: string | null = null;
      if (effective.provider === "tushare") {
        if (effective.tokenEnvelope === null) throw new Error("missing Tushare token");
        token = decryptToken(effective.tokenEnvelope, key);
      }
      return {
        schemaVersion: "market-data-worker-settings-v1",
        provider: effective.provider,
        revision: effective.revision,
        token,
      };
    } catch {
      throw new ServiceUnavailableException("行情源配置暂时不可用");
    }
  }

  private resolveTokenEnvelope(
    request: MarketDataSettingsUpdateRequest,
    current: PersistedMarketDataSettings | null,
  ) {
    if (request.provider === "tushare" && request.tokenAction === "CLEAR") {
      throw new BadRequestException("Tushare 必须保留有效 token");
    }
    if (request.tokenAction === "KEEP") {
      if (request.token !== undefined) throw new BadRequestException("KEEP 不接受 token");
      if (request.provider === "tushare" && (current === null || current.tokenEnvelope === null)) {
        throw new BadRequestException("Tushare 需要先配置 token");
      }
      if (request.provider === "tushare" && current?.tokenEnvelope !== undefined) {
        if (current.tokenEnvelope === null)
          throw new BadRequestException("Tushare 需要先配置 token");
        try {
          validateToken(decryptToken(current.tokenEnvelope, this.keyProvider.getKey()));
        } catch {
          throw new ServiceUnavailableException("行情源配置暂时不可用");
        }
      }
      return current?.tokenEnvelope ?? null;
    }
    if (request.tokenAction === "CLEAR") return null;
    if (request.token === undefined) throw new BadRequestException("REPLACE 必须提供 token");
    try {
      return encryptToken(request.token, this.keyProvider.getKey());
    } catch {
      throw new ServiceUnavailableException("行情源配置暂时不可用");
    }
  }

  private assertAdministrator(userId: string, roles: readonly string[]): void {
    if (!UUID.test(userId) || roles.length !== 1 || roles[0] !== "platform_admin") {
      throw new ForbiddenException("无权访问行情源配置");
    }
  }

  private now(): string {
    const now = this.clock();
    if (!Number.isFinite(now.getTime()))
      throw new ServiceUnavailableException("行情源配置暂时不可用");
    return now.toISOString();
  }
}

function parseUpdateRequest(input: unknown): MarketDataSettingsUpdateRequest {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    throw new BadRequestException("行情源配置请求无效");
  }
  const value = input as Record<string, unknown>;
  const expectedKeys = new Set([
    "schemaVersion",
    "expectedRevision",
    "provider",
    "tokenAction",
    "token",
  ]);
  if (Object.keys(value).some((key) => !expectedKeys.has(key))) {
    throw new BadRequestException("行情源配置请求无效");
  }
  if (
    value.schemaVersion !== "market-data-settings-update-v1" ||
    !Number.isSafeInteger(value.expectedRevision) ||
    (value.expectedRevision as number) < 0 ||
    typeof value.provider !== "string" ||
    !PROVIDERS.has(value.provider as MarketDataProvider) ||
    typeof value.tokenAction !== "string" ||
    !TOKEN_ACTIONS.has(value.tokenAction as MarketDataTokenAction)
  ) {
    throw new BadRequestException("行情源配置请求无效");
  }
  const token = value.token;
  const action = value.tokenAction as MarketDataTokenAction;
  if (action === "REPLACE") {
    try {
      validateToken(token);
    } catch {
      throw new BadRequestException("token 格式无效");
    }
  } else if (token !== undefined) {
    throw new BadRequestException("KEEP/CLEAR 不接受 token");
  }
  return {
    schemaVersion: "market-data-settings-update-v1",
    expectedRevision: value.expectedRevision as number,
    provider: value.provider as MarketDataProvider,
    tokenAction: action,
    ...(token === undefined ? {} : { token }),
  };
}

function defaultSettings(): PersistedMarketDataSettings {
  return {
    provider: "akshare",
    revision: 0,
    tokenEnvelope: null,
    updatedAt: null,
  };
}

function toBrowserResponse(
  persisted: PersistedMarketDataSettings | null,
): MarketDataSettingsResponse {
  const settings = persisted ?? defaultSettings();
  return {
    schemaVersion: "market-data-settings-v1",
    provider: settings.provider,
    revision: settings.revision,
    tokenConfigured: envelopeConfigured(settings.tokenEnvelope),
    updatedAt: settings.updatedAt,
  };
}
