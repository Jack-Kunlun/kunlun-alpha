import { describe, expect, it, vi } from "vitest";
import type { PasswordHasher } from "./modules/auth/password";
import {
  parseBootstrapArguments,
  provisionFirstAdministrator,
  type AdministratorBootstrapStore,
} from "./auth-bootstrap";

describe("local administrator bootstrap", () => {
  it("hashes the interactive password and persists no plaintext", async () => {
    const createFirstAdministrator = vi.fn();
    const store: AdministratorBootstrapStore = { createFirstAdministrator };
    const hasher = {
      hash: vi.fn().mockResolvedValue("$scrypt$v=1$encoded"),
      verify: vi.fn(),
      consumeDummy: vi.fn(),
    } as unknown as PasswordHasher;

    await provisionFirstAdministrator(
      store,
      hasher,
      { username: " Admin ", displayName: "本地管理员" },
      "correct horse battery staple",
    );

    expect(hasher.hash).toHaveBeenCalledWith("correct horse battery staple");
    expect(createFirstAdministrator).toHaveBeenCalledWith(
      expect.objectContaining({
        username: "admin",
        passwordHash: "$scrypt$v=1$encoded",
        roles: ["platform_admin"],
      }),
    );
    expect(JSON.stringify(createFirstAdministrator.mock.calls)).not.toContain(
      "correct horse battery staple",
    );
  });

  it("parses only bounded bootstrap arguments", () => {
    expect(
      parseBootstrapArguments(["--username", "operator", "--display-name", "研究管理员"]),
    ).toEqual({ username: "operator", displayName: "研究管理员" });
    expect(() => parseBootstrapArguments(["--password", "secret"])).toThrow("argument");
  });
});
