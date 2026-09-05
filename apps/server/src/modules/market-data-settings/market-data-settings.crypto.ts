import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import {
  MARKET_DATA_SETTINGS_ENCRYPTION_VERSION,
  MARKET_DATA_SETTINGS_INSTANCE_ID,
  MARKET_DATA_SETTINGS_KEY_VERSION,
  type EncryptedTokenEnvelope,
  type MarketDataSettingsKeyProvider,
} from "./market-data-settings.types";

const KEY_BYTES = 32;
const NONCE_BYTES = 12;
const TAG_BYTES = 16;
const TOKEN_PATTERN = /^[\x21-\x7e]+$/;
const AAD_PREFIX = "kunlun-alpha:market-data-settings:token";

export class MarketDataSettingsCryptoError extends Error {
  constructor() {
    super("market-data settings secret operation unavailable");
    this.name = "MarketDataSettingsCryptoError";
  }
}

export class LazyMasterKeyProvider implements MarketDataSettingsKeyProvider {
  private key: Buffer | undefined;

  constructor(private readonly readKey: () => Buffer) {}

  getKey(): Buffer {
    if (this.key === undefined) this.key = Buffer.from(this.readKey());
    return Buffer.from(this.key);
  }
}

export class DisabledMasterKeyProvider implements MarketDataSettingsKeyProvider {
  getKey(): Buffer {
    throw new MarketDataSettingsCryptoError();
  }
}

export function createMasterKeyProvider(
  environ: Readonly<Record<string, string | undefined>>,
): MarketDataSettingsKeyProvider {
  const encodedValue = environ["MARKET_DATA_SETTINGS_MASTER_KEY"];
  const fileValue = environ["MARKET_DATA_SETTINGS_MASTER_KEY_FILE"];
  const encoded =
    encodedValue !== undefined && encodedValue.trim() !== "" ? encodedValue : undefined;
  const file = fileValue !== undefined && fileValue.trim() !== "" ? fileValue : undefined;
  return new LazyMasterKeyProvider(() => {
    if ((encoded === undefined) === (file === undefined)) {
      throw new MarketDataSettingsCryptoError();
    }
    const source = encoded ?? readFileSync(file as string, "utf8");
    return decodeKey(source);
  });
}

export function validateToken(token: unknown): asserts token is string {
  if (
    typeof token !== "string" ||
    token.length < 1 ||
    token.length > 256 ||
    !TOKEN_PATTERN.test(token)
  ) {
    throw new MarketDataSettingsCryptoError();
  }
}

export function encryptToken(token: string, key: Buffer): EncryptedTokenEnvelope {
  validateToken(token);
  assertKey(key);
  const nonce = randomBytes(NONCE_BYTES);
  const cipher = createCipheriv("aes-256-gcm", key, nonce);
  cipher.setAAD(aad(MARKET_DATA_SETTINGS_KEY_VERSION));
  const ciphertext = Buffer.concat([cipher.update(token, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  if (tag.length !== TAG_BYTES) throw new MarketDataSettingsCryptoError();
  return {
    ciphertext: encodeBase64(ciphertext),
    nonce: encodeBase64(nonce),
    tag: encodeBase64(tag),
    encryptionVersion: MARKET_DATA_SETTINGS_ENCRYPTION_VERSION,
    keyVersion: MARKET_DATA_SETTINGS_KEY_VERSION,
  };
}

export function decryptToken(envelope: EncryptedTokenEnvelope, key: Buffer): string {
  assertEnvelope(envelope);
  assertKey(key);
  const nonce = decodeBase64(envelope.nonce, NONCE_BYTES);
  const tag = decodeBase64(envelope.tag, TAG_BYTES);
  const ciphertext = decodeBase64(envelope.ciphertext, 1, 256);
  const decipher = createDecipheriv("aes-256-gcm", key, nonce);
  decipher.setAAD(aad(envelope.keyVersion));
  decipher.setAuthTag(tag);
  try {
    const token = Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8");
    validateToken(token);
    return token;
  } catch {
    throw new MarketDataSettingsCryptoError();
  }
}

export function envelopeConfigured(envelope: EncryptedTokenEnvelope | null): boolean {
  return envelope !== null;
}

function aad(keyVersion: string): Buffer {
  return Buffer.from(
    `${AAD_PREFIX}:${MARKET_DATA_SETTINGS_INSTANCE_ID}:${MARKET_DATA_SETTINGS_ENCRYPTION_VERSION}:${keyVersion}`,
    "utf8",
  );
}

function assertKey(key: Buffer): void {
  if (!Buffer.isBuffer(key) || key.length !== KEY_BYTES) throw new MarketDataSettingsCryptoError();
}

function assertEnvelope(envelope: EncryptedTokenEnvelope): void {
  if (
    envelope.encryptionVersion !== MARKET_DATA_SETTINGS_ENCRYPTION_VERSION ||
    envelope.keyVersion !== MARKET_DATA_SETTINGS_KEY_VERSION
  ) {
    throw new MarketDataSettingsCryptoError();
  }
}

function decodeKey(source: string): Buffer {
  if (typeof source !== "string") throw new MarketDataSettingsCryptoError();
  const encoded = source.trim();
  const key = decodeBase64(encoded, KEY_BYTES, KEY_BYTES);
  return key;
}

function encodeBase64(value: Buffer): string {
  return value.toString("base64");
}

function decodeBase64(value: string, minBytes: number, maxBytes = minBytes): Buffer {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length % 4 === 1 ||
    !/^[A-Za-z0-9+/]*={0,2}$/.test(value)
  ) {
    throw new MarketDataSettingsCryptoError();
  }
  const decoded = Buffer.from(value, "base64");
  if (
    decoded.length < minBytes ||
    decoded.length > maxBytes ||
    decoded.toString("base64") !== value
  ) {
    throw new MarketDataSettingsCryptoError();
  }
  return decoded;
}
