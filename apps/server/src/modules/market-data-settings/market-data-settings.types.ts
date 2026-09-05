import type {
  MarketDataProvider,
  MarketDataSettingsResponse,
  MarketDataSettingsUpdateRequest,
  MarketDataTokenAction,
  MarketDataWorkerSettingsResponse,
} from "@kunlun/shared-types";

export const MARKET_DATA_SETTINGS_INSTANCE_ID = "default";
export const MARKET_DATA_SETTINGS_ENCRYPTION_VERSION = "aes-256-gcm-v1";
export const MARKET_DATA_SETTINGS_KEY_VERSION = "v1";

export interface EncryptedTokenEnvelope {
  ciphertext: string;
  nonce: string;
  tag: string;
  encryptionVersion: typeof MARKET_DATA_SETTINGS_ENCRYPTION_VERSION;
  keyVersion: string;
}

export interface PersistedMarketDataSettings {
  provider: MarketDataProvider;
  revision: number;
  tokenEnvelope: EncryptedTokenEnvelope | null;
  updatedAt: string | null;
}

export interface MarketDataSettingsRepository {
  get(): Promise<PersistedMarketDataSettings | null>;
  compareAndSet(input: {
    expectedRevision: number;
    provider: MarketDataProvider;
    tokenEnvelope: EncryptedTokenEnvelope | null;
    tokenAction: MarketDataTokenAction;
    actorId: string;
    updatedAt: string;
  }): Promise<PersistedMarketDataSettings>;
}

export interface MarketDataSettingsKeyProvider {
  getKey(): Buffer;
}

export interface MarketDataSettingsServicePort {
  getBrowserSettings(userId: string, roles: readonly string[]): Promise<MarketDataSettingsResponse>;
  updateBrowserSettings(
    userId: string,
    roles: readonly string[],
    input: unknown,
  ): Promise<MarketDataSettingsResponse>;
  getWorkerSettings(): Promise<MarketDataWorkerSettingsResponse>;
}

export type {
  MarketDataProvider,
  MarketDataSettingsResponse,
  MarketDataSettingsUpdateRequest,
  MarketDataTokenAction,
  MarketDataWorkerSettingsResponse,
};
