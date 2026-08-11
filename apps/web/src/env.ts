/**
 * Typed browser environment variables.
 *
 * Only variables prefixed with `VITE_` are exposed to the client.
 * Server-side secrets (API keys, DB passwords, etc.) MUST NOT appear here.
 */
function requireEnv(key: string): string {
  const value = import.meta.env[key];
  if (value === undefined) {
    throw new Error(`Missing required env variable: ${key}`);
  }
  return value;
}

const env = {
  /** Application title */
  TITLE: String(import.meta.env.VITE_APP_TITLE ?? "昆仑智策"),
  /** API base URL — only the public gateway, never a secret */
  API_URL: String(import.meta.env.VITE_API_URL ?? "/api"),
  /** Whether running in production mode */
  PROD: import.meta.env.PROD,
  /** Whether running in development mode */
  DEV: import.meta.env.DEV,
} as const;

export { env, requireEnv };
export type Env = typeof env;
