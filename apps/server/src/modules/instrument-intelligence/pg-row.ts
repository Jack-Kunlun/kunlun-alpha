export function pgText(value: unknown, field: string): string {
  if (typeof value !== "string" || value === "") {
    throw new Error("invalid PostgreSQL intelligence field: " + field);
  }
  return value;
}

export function pgInstant(value: unknown, field: string): string {
  const instant = value instanceof Date ? value.toISOString() : pgText(value, field);
  if (!Number.isFinite(Date.parse(instant))) {
    throw new Error("invalid PostgreSQL intelligence instant: " + field);
  }
  return new Date(instant).toISOString();
}

export function pgBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error("invalid PostgreSQL intelligence field: " + field);
  }
  return value;
}

export function sourceVersion(source: string, version: string): string {
  return source + "@" + version;
}
