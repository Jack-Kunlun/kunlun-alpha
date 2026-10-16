import { describe, expect, it } from "vitest";
import {
  canAccessTerminalRoute,
  getTerminalRoute,
  terminalRoutes,
  visibleTerminalRoutes,
} from "./route-contract";

describe("terminal route contract", () => {
  it("keeps route identifiers and paths unique", () => {
    expect(new Set(terminalRoutes.map((route) => route.id)).size).toBe(terminalRoutes.length);
    expect(new Set(terminalRoutes.map((route) => route.path)).size).toBe(terminalRoutes.length);
  });

  it("reserves stable deep links for every current decision and workspace surface", () => {
    expect(terminalRoutes.map((route) => route.path)).toEqual(
      expect.arrayContaining([
        "/",
        "/market-overview",
        "/limit-pool",
        "/rotation",
        "/ranking",
        "/instruments",
        "/instruments/:instrumentId",
        "/watchlists",
        "/paper",
        "/precious-metals",
        "/settings/market-data",
      ]),
    );
  });

  it("applies the role matrix without exposing operations or paper routes to viewers", () => {
    const viewerRoutes = visibleTerminalRoutes(["viewer"]);
    expect(viewerRoutes.map((route) => route.id)).toEqual([
      "home",
      "market-overview",
      "instruments",
      "watchlists",
    ]);
    expect(viewerRoutes.map((route) => route.id)).not.toContain("paper");
    expect(viewerRoutes.map((route) => route.id)).not.toContain("data-quality");
    expect(canAccessTerminalRoute(getTerminalRoute("paper"), ["paper_operator"])).toBe(true);
    expect(terminalRoutes.every((route) => canAccessTerminalRoute(route, ["platform_admin"]))).toBe(
      true,
    );
  });

  it("limits the 1.0 navigation and ready routes to the daily research surface", () => {
    expect(
      terminalRoutes.filter((route) => route.status === "ready").map((route) => route.id),
    ).toEqual(["home", "market-overview", "instruments", "instrument-detail", "watchlists"]);
    expect(terminalRoutes.filter((route) => route.navigation).map((route) => route.id)).toEqual([
      "home",
      "market-overview",
      "instruments",
      "watchlists",
    ]);
    expect(
      terminalRoutes
        .filter((route) => route.status === "planned")
        .every((route) => !route.navigation),
    ).toBe(true);
  });

  it("keeps market-data settings instance-scoped and administrator-only", () => {
    const route = getTerminalRoute("market-data-settings");
    expect(route.path).toBe("/settings/market-data");
    expect(route.group).toBe("research");
    expect(route.permission).toBe("operations:read");
    expect(route.navigation).toBe(false);
    expect(route.status).toBe("planned");
    expect(canAccessTerminalRoute(route, ["platform_admin"])).toBe(true);
    expect(canAccessTerminalRoute(route, ["researcher"])).toBe(false);
  });
});
