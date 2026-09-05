import type {
  MarketDataProvider,
  MarketDataSettingsResponse,
  MarketDataSettingsUpdateRequest as SharedMarketDataSettingsUpdateRequest,
  MarketDataTokenAction,
} from "@kunlun/shared-types";
import { ApiError, apiClient, type ApiClient } from "@/lib/api-client";

export const MARKET_DATA_SETTINGS_API_PATH = "/v1/market-data/settings";

const RESPONSE_KEYS = [
  "schemaVersion",
  "provider",
  "revision",
  "tokenConfigured",
  "updatedAt",
] as const;

const PROVIDERS: readonly MarketDataProvider[] = ["akshare", "tushare"];
const TOKEN_ACTIONS: readonly MarketDataTokenAction[] = ["KEEP", "REPLACE", "CLEAR"];
const TOKEN_PATTERN = /^[\x21-\x7e]+$/;
const ISO_DATE_TIME_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?(?:Z|[+-]\d{2}:\d{2})$/;

export type MarketDataSettingsUpdatePayload = SharedMarketDataSettingsUpdateRequest;

export interface MarketDataSettingsDraft {
  expectedRevision: number;
  provider: MarketDataProvider;
  tokenAction: MarketDataTokenAction;
  token: string;
}

function invalidResponse(): Error {
  return new Error("行情源配置响应无效");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && actual.every((key) => keys.includes(key));
}

export function isMarketDataProvider(value: unknown): value is MarketDataProvider {
  return typeof value === "string" && PROVIDERS.includes(value as MarketDataProvider);
}

export function isMarketDataTokenAction(value: unknown): value is MarketDataTokenAction {
  return typeof value === "string" && TOKEN_ACTIONS.includes(value as MarketDataTokenAction);
}

export function isValidMarketDataToken(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 256 &&
    TOKEN_PATTERN.test(value)
  );
}

function isValidUpdatedAt(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === "string" &&
      ISO_DATE_TIME_PATTERN.test(value) &&
      Number.isFinite(Date.parse(value)))
  );
}

/**
 * Runtime boundary for browser responses. The server contract deliberately
 * excludes credentials; rejecting extra keys prevents accidental secret
 * propagation if that boundary regresses.
 */
export function validateMarketDataSettingsResponse(value: unknown): MarketDataSettingsResponse {
  if (!isRecord(value) || !hasExactKeys(value, RESPONSE_KEYS)) throw invalidResponse();
  const revision = value.revision;
  if (
    value.schemaVersion !== "market-data-settings-v1" ||
    !isMarketDataProvider(value.provider) ||
    typeof revision !== "number" ||
    !Number.isSafeInteger(revision) ||
    revision < 0 ||
    typeof value.tokenConfigured !== "boolean" ||
    !isValidUpdatedAt(value.updatedAt)
  ) {
    throw invalidResponse();
  }
  return {
    schemaVersion: "market-data-settings-v1",
    provider: value.provider,
    revision,
    tokenConfigured: value.tokenConfigured,
    updatedAt: value.updatedAt,
  };
}

/**
 * Build the compare-and-set request. KEEP/CLEAR intentionally omit token,
 * while REPLACE is the only action that can carry a token.
 */
export function buildMarketDataSettingsUpdate(
  draft: MarketDataSettingsDraft,
): MarketDataSettingsUpdatePayload {
  if (!Number.isSafeInteger(draft.expectedRevision) || draft.expectedRevision < 0) {
    throw new Error("行情源配置 revision 无效");
  }
  if (!isMarketDataProvider(draft.provider) || !isMarketDataTokenAction(draft.tokenAction)) {
    throw new Error("行情源配置请求无效");
  }
  const base = {
    schemaVersion: "market-data-settings-update-v1" as const,
    expectedRevision: draft.expectedRevision,
    provider: draft.provider,
    tokenAction: draft.tokenAction,
  };
  if (draft.tokenAction === "REPLACE") {
    if (!isValidMarketDataToken(draft.token)) throw new Error("token 格式无效");
    return { ...base, token: draft.token };
  }
  if (draft.token !== "") throw new Error("KEEP/CLEAR 不接受 token");
  return base;
}

function validateMarketDataSettingsUpdate(value: unknown): MarketDataSettingsUpdatePayload {
  if (!isRecord(value)) throw new Error("行情源配置请求无效");
  const keys = Object.keys(value);
  if (
    keys.some(
      (key) =>
        !["schemaVersion", "expectedRevision", "provider", "tokenAction", "token"].includes(key),
    )
  ) {
    throw new Error("行情源配置请求无效");
  }
  if (
    value.schemaVersion !== "market-data-settings-update-v1" ||
    typeof value.expectedRevision !== "number" ||
    !isMarketDataProvider(value.provider) ||
    !isMarketDataTokenAction(value.tokenAction)
  ) {
    throw new Error("行情源配置请求无效");
  }
  const action = value.tokenAction;
  const token = value.token;
  if (action === "REPLACE" && typeof token !== "string") {
    throw new Error("token 格式无效");
  }
  if (action !== "REPLACE" && token !== undefined) {
    throw new Error("KEEP/CLEAR 不接受 token");
  }
  return buildMarketDataSettingsUpdate({
    expectedRevision: value.expectedRevision,
    provider: value.provider,
    tokenAction: action,
    token: typeof token === "string" ? token : "",
  });
}

export async function getMarketDataSettings(
  client: ApiClient = apiClient,
): Promise<MarketDataSettingsResponse> {
  return validateMarketDataSettingsResponse(
    await client.get<unknown>(MARKET_DATA_SETTINGS_API_PATH),
  );
}

export async function updateMarketDataSettings(
  client: ApiClient,
  update: MarketDataSettingsUpdatePayload,
): Promise<MarketDataSettingsResponse> {
  const validated = validateMarketDataSettingsUpdate(update);
  return validateMarketDataSettingsResponse(
    await client.post<MarketDataSettingsUpdatePayload, unknown>(
      MARKET_DATA_SETTINGS_API_PATH,
      validated,
    ),
  );
}

/** Never use backend error text in the UI; status codes select fixed copy. */
export function marketDataSettingsErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 400) return "保存失败：行情源配置请求无效";
    if (error.status === 403) return "无权访问行情源配置";
    if (error.status === 409) return "配置已被其他操作更新，请刷新后再重试";
    if (error.status === 503) return "行情源配置服务暂时不可用，请稍后重试";
  }
  return "行情源配置暂时不可用，请稍后重试";
}

export function isDefaultMarketDataSettings(value: MarketDataSettingsResponse): boolean {
  return value.revision === 0 && value.updatedAt === null;
}
