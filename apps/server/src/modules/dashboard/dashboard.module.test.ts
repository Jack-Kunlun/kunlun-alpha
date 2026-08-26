import { describe, expect, it } from "vitest";
import { dashboardAuthorizerFor } from "./dashboard.module";

describe("dashboard deployment authorization", () => {
  it("fails closed unless public terminal read is explicitly enabled", async () => {
    expect(await dashboardAuthorizerFor(undefined).canAccess()).toBe(false);
    expect(await dashboardAuthorizerFor("deny").canAccess()).toBe(false);
    expect(await dashboardAuthorizerFor("public").canAccess()).toBe(true);
    expect(() => dashboardAuthorizerFor("allow")).toThrow(
      "DASHBOARD_TERMINAL_READ_POLICY must be deny or public",
    );
  });
});
