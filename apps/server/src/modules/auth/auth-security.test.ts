import { describe, expect, it } from "vitest";
import {
  assertInternalServiceRequest,
  assertTrustedBrowserRequest,
  loadAuthConfig,
  readCookieToken,
} from "./auth.config";
import { normalizeUsername, ScryptPasswordHasher, validatePassword } from "./password";

describe("authentication configuration and browser boundary", () => {
  it("permits an explicitly insecure cookie only for an explicit loopback origin", () => {
    expect(
      loadAuthConfig({
        NODE_ENV: "development",
        AUTH_PUBLIC_ORIGIN: "http://localhost:5173",
        AUTH_ALLOW_INSECURE_COOKIE: "true",
        KUNLUN_POSTGRES_DSN: "postgresql://local.invalid/kunlun",
      }),
    ).toMatchObject({
      cookieName: "kunlun_session",
      secureCookie: false,
      publicOrigin: "http://localhost:5173",
    });
    expect(
      loadAuthConfig({
        NODE_ENV: "production",
        AUTH_PUBLIC_ORIGIN: "http://localhost:5173",
        AUTH_ALLOW_INSECURE_COOKIE: "true",
        KUNLUN_POSTGRES_DSN: "postgresql://local.invalid/kunlun",
      }),
    ).toMatchObject({ cookieName: "kunlun_session", secureCookie: false });
    expect(() =>
      loadAuthConfig({
        NODE_ENV: "development",
        AUTH_PUBLIC_ORIGIN: "http://example.test",
        AUTH_ALLOW_INSECURE_COOKIE: "true",
        KUNLUN_POSTGRES_DSN: "postgresql://local.invalid/kunlun",
      }),
    ).toThrow("loopback");
  });

  it("requires an exact browser origin and rejects cross-site fetch metadata", () => {
    expect(() =>
      assertTrustedBrowserRequest(
        { origin: "http://localhost:5173", secFetchSite: "same-origin" },
        "http://localhost:5173",
      ),
    ).not.toThrow();
    expect(() =>
      assertTrustedBrowserRequest(
        { referer: "http://localhost:5173/login", secFetchSite: "same-site" },
        "http://localhost:5173",
      ),
    ).not.toThrow();
    expect(() =>
      assertTrustedBrowserRequest(
        { origin: "https://evil.example", secFetchSite: "cross-site" },
        "http://localhost:5173",
      ),
    ).toThrow("origin");
  });

  it("extracts one exact base64url session cookie and fails closed on duplicates", () => {
    const token = "a".repeat(43);
    expect(readCookieToken(`theme=dark; kunlun_session=${token}`, "kunlun_session")).toBe(token);
    expect(
      readCookieToken(`kunlun_session=${token}; kunlun_session=${token}`, "kunlun_session"),
    ).toBe(null);
    expect(readCookieToken("kunlun_session=not-a-session", "kunlun_session")).toBe(null);
  });

  it("keeps the internal worker credential separate from browser authentication", () => {
    const token = "w".repeat(32);
    expect(
      loadAuthConfig({
        AUTH_PUBLIC_ORIGIN: "http://localhost:5173",
        AUTH_ALLOW_INSECURE_COOKIE: "true",
        KUNLUN_POSTGRES_DSN: "postgresql://local.invalid/kunlun",
        MARKET_DATA_SETTINGS_WORKER_TOKEN: token,
      }).marketDataSettingsWorkerToken,
    ).toBe(token);
    expect(() =>
      assertInternalServiceRequest(
        { authorization: `Bearer ${token}` },
        "GET",
        "/api/v1/internal/market-data/settings",
        token,
      ),
    ).not.toThrow();
    expect(() =>
      assertInternalServiceRequest(
        { authorization: `Bearer ${token}`, origin: "http://localhost:5173" },
        "GET",
        "/api/v1/internal/market-data/settings",
        token,
      ),
    ).toThrow();
    expect(
      loadAuthConfig({
        AUTH_PUBLIC_ORIGIN: "http://localhost:5173",
        AUTH_ALLOW_INSECURE_COOKIE: "true",
        KUNLUN_POSTGRES_DSN: "postgresql://local.invalid/kunlun",
        MARKET_DATA_SETTINGS_WORKER_TOKEN: "short",
      }).marketDataSettingsWorkerToken,
    ).toBeUndefined();
  });
});

describe("scrypt administrator passwords", () => {
  it("normalizes a bounded ASCII username and rejects short passwords", () => {
    expect(normalizeUsername(" Admin ")).toBe("admin");
    expect(() => normalizeUsername("管理员")).toThrow("username");
    expect(() => validatePassword("too-short")).toThrow("password");
  });

  it("stores a versioned salted scrypt hash and compares without plaintext persistence", async () => {
    const hasher = new ScryptPasswordHasher({ cost: 1024, maxmem: 8 * 1024 * 1024 });
    const encoded = await hasher.hash("correct horse battery staple");

    expect(encoded).toMatch(/^\$scrypt\$v=1\$N=1024,r=8,p=1\$/);
    await expect(hasher.verify("correct horse battery staple", encoded)).resolves.toBe(true);
    await expect(hasher.verify("wrong password value", encoded)).resolves.toBe(false);
    await expect(hasher.verify("correct horse battery staple", "$scrypt$broken")).resolves.toBe(
      false,
    );
  });

  it("surfaces verifier capacity exhaustion instead of treating it as a bad password", async () => {
    const hasher = new ScryptPasswordHasher({
      cost: 1024,
      maxmem: 8 * 1024 * 1024,
      maximumConcurrent: 1,
      maximumQueued: 0,
    });
    const encoded = await hasher.hash("correct horse battery staple");

    const busy = hasher.hash("another correct password value");
    await expect(hasher.verify("correct horse battery staple", encoded)).rejects.toThrow(
      "capacity",
    );
    await busy;
  });
});
