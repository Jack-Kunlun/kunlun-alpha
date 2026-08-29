import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const schema = JSON.parse(readFileSync("schemas/auth/session.json", "utf8")) as Record<
  string,
  unknown
>;

describe("authenticated session response contract", () => {
  it("is closed, versioned and limited to the local platform administrator role", () => {
    expect(schema["title"]).toBe("AuthSessionResponse");
    expect(schema["additionalProperties"]).toBe(false);
    expect(JSON.stringify(schema)).toContain("auth-session-v1");
    expect(JSON.stringify(schema)).toContain("platform_admin");
    expect(schema["required"]).toEqual(
      expect.arrayContaining([
        "schemaVersion",
        "authenticated",
        "user",
        "csrfToken",
        "absoluteExpiresAt",
        "idleExpiresAt",
      ]),
    );
  });
});
