import { randomUUID } from "node:crypto";
import { Pool, type PoolClient } from "pg";
import {
  normalizeUsername,
  type PasswordHasher,
  ScryptPasswordHasher,
} from "./modules/auth/password";

export interface AdministratorBootstrapInput {
  username: string;
  displayName: string;
}

export interface NewAdministratorRecord {
  userId: string;
  username: string;
  displayName: string;
  passwordHash: string;
  roles: ["platform_admin"];
  createdAt: string;
}

export interface AdministratorBootstrapStore {
  createFirstAdministrator(record: NewAdministratorRecord): Promise<void>;
}

export class PostgresAdministratorBootstrapStore implements AdministratorBootstrapStore {
  constructor(private readonly pool: Pool) {}

  async createFirstAdministrator(record: NewAdministratorRecord): Promise<void> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock(hashtext($1))", [
        "kunlun-alpha.auth.first-administrator",
      ]);
      const existing = await client.query<{ user_count: string }>(
        "SELECT count(*) AS user_count FROM auth_users",
      );
      if (Number(existing.rows[0]?.user_count ?? "0") !== 0) {
        throw new Error("an authentication user already exists; bootstrap is create-only");
      }
      await client.query(
        `INSERT INTO auth_users (
           user_id, username, display_name, password_hash, roles,
           disabled, created_at, updated_at
         ) VALUES ($1, $2, $3, $4, $5::jsonb, false, $6::timestamptz, $6::timestamptz)`,
        [
          record.userId,
          record.username,
          record.displayName,
          record.passwordHash,
          JSON.stringify(record.roles),
          record.createdAt,
        ],
      );
      await client.query("COMMIT");
    } catch (error) {
      await rollback(client);
      throw error;
    } finally {
      client.release();
    }
  }
}

async function rollback(client: PoolClient): Promise<void> {
  try {
    await client.query("ROLLBACK");
  } catch {
    // Preserve the original failure; the client is released immediately below.
  }
}

export function parseBootstrapArguments(args: readonly string[]): AdministratorBootstrapInput {
  let username = "admin";
  let displayName = "本地管理员";
  for (let index = 0; index < args.length; index += 2) {
    const name = args[index];
    const value = args[index + 1];
    if (value === undefined) throw new Error("bootstrap argument requires a value");
    if (name === "--username") username = value;
    else if (name === "--display-name") displayName = value;
    else throw new Error(`unsupported bootstrap argument: ${name ?? ""}`);
  }
  if (displayName.length < 1 || displayName.length > 80) {
    throw new Error("display name must contain 1-80 characters");
  }
  return { username: normalizeUsername(username), displayName };
}

export async function provisionFirstAdministrator(
  store: AdministratorBootstrapStore,
  hasher: PasswordHasher,
  input: AdministratorBootstrapInput,
  password: string,
): Promise<void> {
  const username = normalizeUsername(input.username);
  if (input.displayName.length < 1 || input.displayName.length > 80) {
    throw new Error("display name must contain 1-80 characters");
  }
  const passwordHash = await hasher.hash(password);
  await store.createFirstAdministrator({
    userId: randomUUID(),
    username,
    displayName: input.displayName,
    passwordHash,
    roles: ["platform_admin"],
    createdAt: new Date().toISOString(),
  });
}

async function readSecret(prompt: string): Promise<string> {
  const input = process.stdin;
  if (!input.isTTY || typeof input.setRawMode !== "function" || !process.stdout.isTTY) {
    throw new Error("administrator password bootstrap requires an interactive TTY");
  }
  process.stdout.write(prompt);
  input.setEncoding("utf8");
  input.setRawMode(true);
  input.resume();
  return new Promise<string>((resolve, reject) => {
    let value = "";
    const finish = (error?: Error) => {
      input.off("data", onData);
      input.setRawMode(false);
      input.pause();
      process.stdout.write("\n");
      if (error !== undefined) reject(error);
      else resolve(value);
    };
    const onData = (chunk: string | Buffer) => {
      for (const character of String(chunk)) {
        if (character === "\u0003" || character === "\u0004") {
          finish(new Error("administrator password bootstrap was cancelled"));
          return;
        }
        if (character === "\r" || character === "\n") {
          finish();
          return;
        }
        if (character === "\u007f" || character === "\b") value = value.slice(0, -1);
        else value += character;
      }
    };
    input.on("data", onData);
  });
}

async function main(): Promise<void> {
  const dsn = process.env["AUTH_POSTGRES_DSN"] ?? process.env["KUNLUN_POSTGRES_DSN"];
  if (!dsn?.trim()) throw new Error("AUTH_POSTGRES_DSN is required for administrator bootstrap");
  const input = parseBootstrapArguments(process.argv.slice(2));
  const password = await readSecret("管理员密码（不会回显）：");
  const confirmation = await readSecret("再次输入管理员密码：");
  if (password !== confirmation) throw new Error("两次输入的管理员密码不一致");
  const pool = new Pool({ connectionString: dsn });
  try {
    await provisionFirstAdministrator(
      new PostgresAdministratorBootstrapStore(pool),
      new ScryptPasswordHasher(),
      input,
      password,
    );
    console.log(`本地管理员已创建：${input.username}`);
  } finally {
    await pool.end();
  }
}

if (require.main === module) {
  void main().catch((error: unknown) => {
    console.error("本地管理员创建失败：", error instanceof Error ? error.message : "unknown error");
    process.exitCode = 1;
  });
}
