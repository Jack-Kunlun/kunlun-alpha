import { randomBytes, scrypt, timingSafeEqual } from "node:crypto";

const USERNAME = /^[a-z0-9][a-z0-9._-]{2,63}$/;
const PASSWORD_MIN_CHARACTERS = 12;
const PASSWORD_MAX_BYTES = 256;
const SALT_BYTES = 16;
const DERIVED_KEY_BYTES = 64;
const BLOCK_SIZE = 8;
const PARALLELIZATION = 1;
const PRODUCTION_COST = 2 ** 17;
const PRODUCTION_MAXMEM = 256 * 1024 * 1024;

interface ScryptParameters {
  cost?: number;
  maxmem?: number;
  maximumConcurrent?: number;
  maximumQueued?: number;
}

class ScryptWorkLimiter {
  private active = 0;
  private readonly waiting: Array<() => void> = [];

  constructor(
    private readonly maximumConcurrent: number,
    private readonly maximumQueued: number,
  ) {}

  async run<T>(operation: () => Promise<T>): Promise<T> {
    await this.acquire();
    try {
      return await operation();
    } finally {
      this.release();
    }
  }

  private async acquire(): Promise<void> {
    if (this.active < this.maximumConcurrent) {
      this.active += 1;
      return;
    }
    if (this.waiting.length >= this.maximumQueued) {
      throw new Error("password verification capacity is exhausted");
    }
    await new Promise<void>((resolve) => this.waiting.push(resolve));
  }

  private release(): void {
    const next = this.waiting.shift();
    if (next !== undefined) {
      next();
      return;
    }
    this.active -= 1;
  }
}

function validCost(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 1024 && (value & (value - 1)) === 0;
}

function derive(password: string, salt: Buffer, cost: number, maxmem: number): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    scrypt(
      password,
      salt,
      DERIVED_KEY_BYTES,
      { N: cost, r: BLOCK_SIZE, p: PARALLELIZATION, maxmem },
      (error, key) => {
        if (error) reject(error);
        else resolve(key);
      },
    );
  });
}

function parseEncodedHash(
  encoded: string,
  expectedCost: number,
): { salt: Buffer; expected: Buffer } | null {
  const parts = encoded.split("$");
  if (
    parts.length !== 6 ||
    parts[0] !== "" ||
    parts[1] !== "scrypt" ||
    parts[2] !== "v=1" ||
    !/^[A-Za-z0-9_-]{22}$/.test(parts[4] ?? "") ||
    !/^[A-Za-z0-9_-]{86}$/.test(parts[5] ?? "")
  ) {
    return null;
  }
  const parameters = /^N=(\d+),r=(\d+),p=(\d+)$/.exec(parts[3] ?? "");
  if (parameters === null) return null;
  if (
    Number(parameters[1]) !== expectedCost ||
    Number(parameters[2]) !== BLOCK_SIZE ||
    Number(parameters[3]) !== PARALLELIZATION
  ) {
    return null;
  }
  const salt = Buffer.from(parts[4] ?? "", "base64url");
  const expected = Buffer.from(parts[5] ?? "", "base64url");
  return salt.length === SALT_BYTES && expected.length === DERIVED_KEY_BYTES
    ? { salt, expected }
    : null;
}

export function normalizeUsername(value: string): string {
  const normalized = value.normalize("NFKC").trim().toLowerCase();
  if (!USERNAME.test(normalized)) {
    throw new Error("username must be 3-64 lowercase ASCII letters, digits or ._- characters");
  }
  return normalized;
}

export function validatePassword(value: string): void {
  if (
    value.length < PASSWORD_MIN_CHARACTERS ||
    Buffer.byteLength(value, "utf8") > PASSWORD_MAX_BYTES
  ) {
    throw new Error("password must contain at least 12 characters and at most 256 UTF-8 bytes");
  }
}

export interface PasswordHasher {
  hash(password: string): Promise<string>;
  verify(password: string, encoded: string): Promise<boolean>;
  consumeDummy(password: string): Promise<void>;
}

export class ScryptPasswordHasher implements PasswordHasher {
  private readonly cost: number;
  private readonly maxmem: number;
  private readonly limiter: ScryptWorkLimiter;

  constructor(parameters: ScryptParameters = {}) {
    this.cost = parameters.cost ?? PRODUCTION_COST;
    this.maxmem = parameters.maxmem ?? PRODUCTION_MAXMEM;
    if (!validCost(this.cost))
      throw new Error("scrypt cost must be a power of two of at least 1024");
    if (this.maxmem <= 128 * this.cost * BLOCK_SIZE) {
      throw new Error("scrypt maxmem is too small for the selected cost");
    }
    this.limiter = new ScryptWorkLimiter(
      parameters.maximumConcurrent ?? 2,
      parameters.maximumQueued ?? 8,
    );
  }

  async hash(password: string): Promise<string> {
    validatePassword(password);
    const salt = randomBytes(SALT_BYTES);
    const key = await this.limiter.run(() => derive(password, salt, this.cost, this.maxmem));
    return [
      "",
      "scrypt",
      "v=1",
      `N=${this.cost},r=${BLOCK_SIZE},p=${PARALLELIZATION}`,
      salt.toString("base64url"),
      key.toString("base64url"),
    ].join("$");
  }

  async verify(password: string, encoded: string): Promise<boolean> {
    try {
      validatePassword(password);
    } catch {
      return false;
    }
    const parsed = parseEncodedHash(encoded, this.cost);
    if (parsed === null) return false;
    const actual = await this.limiter.run(() =>
      derive(password, parsed.salt, this.cost, this.maxmem),
    );
    return timingSafeEqual(actual, parsed.expected);
  }

  async consumeDummy(password: string): Promise<void> {
    const bounded =
      Buffer.byteLength(password, "utf8") <= PASSWORD_MAX_BYTES
        ? password
        : "invalid-password-value";
    const candidate = bounded.length >= PASSWORD_MIN_CHARACTERS ? bounded : bounded.padEnd(12, "!");
    await this.limiter.run(() =>
      derive(candidate, Buffer.alloc(SALT_BYTES, 0x5a), this.cost, this.maxmem),
    );
  }
}
