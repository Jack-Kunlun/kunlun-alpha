import { randomBytes } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  decryptToken,
  encryptToken,
  createMasterKeyProvider,
  LazyMasterKeyProvider,
  MarketDataSettingsCryptoError,
  validateToken,
} from "./market-data-settings.crypto";

describe("market-data settings encryption", () => {
  it("round-trips a token with a randomized nonce and no plaintext envelope field", () => {
    const key = randomBytes(32);
    const first = encryptToken("tushare-secret-123", key);
    const second = encryptToken("tushare-secret-123", key);

    expect(first).not.toEqual(second);
    expect(decryptToken(first, key)).toBe("tushare-secret-123");
    expect(JSON.stringify(first)).not.toContain("tushare-secret-123");
  });

  it("fails closed for a wrong key or tampered envelope", () => {
    const envelope = encryptToken("secret", randomBytes(32));
    expect(() => decryptToken(envelope, randomBytes(32))).toThrow(MarketDataSettingsCryptoError);
    expect(() =>
      decryptToken(
        { ...envelope, ciphertext: `${envelope.ciphertext.slice(0, -2)}AA` },
        randomBytes(32),
      ),
    ).toThrow(MarketDataSettingsCryptoError);
  });

  it("rejects unsafe token shapes and invalid master keys", () => {
    expect(() => validateToken("has whitespace")).toThrow(MarketDataSettingsCryptoError);
    expect(() => validateToken("a".repeat(257))).toThrow(MarketDataSettingsCryptoError);
    const provider = new LazyMasterKeyProvider(() => randomBytes(31));
    expect(() => encryptToken("secret", provider.getKey())).toThrow(MarketDataSettingsCryptoError);
  });

  it("treats Compose-style blank key-file values as unset", () => {
    const key = randomBytes(32);
    const provider = createMasterKeyProvider({
      MARKET_DATA_SETTINGS_MASTER_KEY: key.toString("base64"),
      MARKET_DATA_SETTINGS_MASTER_KEY_FILE: "",
    });
    expect(provider.getKey()).toEqual(key);
  });
});
