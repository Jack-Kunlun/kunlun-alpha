import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const schema = JSON.parse(readFileSync("schemas/auth/session-management.json", "utf8")) as Record<
  string,
  unknown
>;

describe("authenticated session management contracts", () => {
  it("keeps session references opaque and versions every response", () => {
    expect(schema["title"]).toBe("AuthSessionListResponse");
    expect(schema["additionalProperties"]).toBe(false);
    const serialized = JSON.stringify(schema);
    expect(serialized).toContain("auth-session-list-v1");
    expect(serialized).toContain("auth-password-change-v1");
    expect(serialized).toContain("auth-session-revocation-v1");
    expect(serialized).not.toContain("sessionDigest");
    expect(serialized).not.toContain("sessionToken");
  });
});
