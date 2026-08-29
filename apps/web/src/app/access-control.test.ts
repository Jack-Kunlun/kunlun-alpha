import { describe, expect, it } from "vitest";
import { resolveBootstrapTerminalRoles } from "./access-control";

describe("terminal role bootstrap", () => {
  it("fails to viewer permissions when a production identity session is absent", () => {
    expect(resolveBootstrapTerminalRoles({ development: false, sessionRoles: undefined })).toEqual([
      "viewer",
    ]);
  });

  it("never grants an administrator role when a development session is absent", () => {
    expect(resolveBootstrapTerminalRoles({ development: true, sessionRoles: undefined })).toEqual([
      "viewer",
    ]);
  });

  it("uses validated server-injected session roles and rejects unknown values", () => {
    expect(
      resolveBootstrapTerminalRoles({
        development: false,
        sessionRoles: ["researcher", "paper_operator", "researcher"],
      }),
    ).toEqual(["researcher", "paper_operator"]);
    expect(
      resolveBootstrapTerminalRoles({
        development: false,
        sessionRoles: ["platform_admin", "root"],
      }),
    ).toEqual(["viewer"]);
  });
});
