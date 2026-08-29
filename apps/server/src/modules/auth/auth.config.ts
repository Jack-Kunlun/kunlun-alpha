export interface AuthConfig {
  postgresDsn: string;
  publicOrigin: string;
  cookieName: string;
  secureCookie: boolean;
  idleTimeoutMs: number;
  absoluteTimeoutMs: number;
  loginWindowMs: number;
  usernameAttemptLimit: number;
  globalAttemptLimit: number;
}

export interface BrowserRequestHeaders {
  origin?: string;
  referer?: string;
  secFetchSite?: string;
}

const SESSION_TOKEN = /^[A-Za-z0-9_-]{43}$/;
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

function exactOrigin(value: string, field: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${field} must be an absolute HTTP(S) origin`);
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash ||
    parsed.origin !== value
  ) {
    throw new Error(`${field} must be an exact HTTP(S) origin`);
  }
  return parsed.origin;
}

function booleanSetting(value: string | undefined, name: string): boolean {
  if (value === undefined || value === "false") return false;
  if (value === "true") return true;
  throw new Error(`${name} must be true or false`);
}

export function loadAuthConfig(environ: Readonly<Record<string, string | undefined>>): AuthConfig {
  const nodeEnv = environ["NODE_ENV"] ?? "development";
  const configuredOrigin = environ["AUTH_PUBLIC_ORIGIN"];
  if (nodeEnv === "production" && configuredOrigin === undefined) {
    throw new Error("AUTH_PUBLIC_ORIGIN is required in production");
  }
  const publicOrigin = exactOrigin(
    configuredOrigin ?? "http://localhost:5173",
    "AUTH_PUBLIC_ORIGIN",
  );
  const insecureCookie = booleanSetting(
    environ["AUTH_ALLOW_INSECURE_COOKIE"],
    "AUTH_ALLOW_INSECURE_COOKIE",
  );
  const origin = new URL(publicOrigin);
  if (insecureCookie) {
    if (origin.protocol !== "http:" || !LOOPBACK_HOSTS.has(origin.hostname)) {
      throw new Error("insecure authentication cookies require an HTTP loopback origin");
    }
  } else if (origin.protocol !== "https:") {
    throw new Error("secure authentication cookies require an HTTPS public origin");
  }

  const postgresDsn =
    environ["AUTH_POSTGRES_DSN"]?.trim() ?? environ["KUNLUN_POSTGRES_DSN"]?.trim();
  if (!postgresDsn) throw new Error("AUTH_POSTGRES_DSN is required");

  return {
    postgresDsn,
    publicOrigin,
    cookieName: insecureCookie ? "kunlun_session" : "__Host-kunlun_session",
    secureCookie: !insecureCookie,
    idleTimeoutMs: 30 * 60 * 1000,
    absoluteTimeoutMs: 8 * 60 * 60 * 1000,
    loginWindowMs: 15 * 60 * 1000,
    usernameAttemptLimit: 8,
    globalAttemptLimit: 50,
  };
}

function referencedOrigin(value: string, field: string): string {
  try {
    return new URL(value).origin;
  } catch {
    throw new Error(`browser ${field} is invalid`);
  }
}

export function assertTrustedBrowserRequest(
  headers: BrowserRequestHeaders,
  allowedOrigin: string,
): void {
  const references: Array<[string, string]> = [];
  if (headers.origin !== undefined) references.push(["origin", headers.origin]);
  if (headers.referer !== undefined) references.push(["referer", headers.referer]);
  if (references.length === 0) throw new Error("browser origin is required");
  for (const [field, value] of references) {
    if (referencedOrigin(value, field) !== allowedOrigin) {
      throw new Error("browser origin is not allowed");
    }
  }
  if (
    headers.secFetchSite !== undefined &&
    headers.secFetchSite !== "same-origin" &&
    headers.secFetchSite !== "same-site"
  ) {
    throw new Error("browser fetch site is not allowed");
  }
}

export function readCookieToken(
  cookieHeader: string | undefined,
  cookieName: string,
): string | null {
  if (cookieHeader === undefined || cookieHeader.length > 8_192) return null;
  const values: string[] = [];
  for (const part of cookieHeader.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    const name = part.slice(0, separator).trim();
    if (name !== cookieName) continue;
    values.push(part.slice(separator + 1).trim());
  }
  if (values.length !== 1 || !SESSION_TOKEN.test(values[0] ?? "")) return null;
  return values[0] ?? null;
}
