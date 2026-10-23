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
    const dataQuality = getTerminalRoute("data-quality");
    expect(dataQuality.permission).toBe("operations:read");
    expect(canAccessTerminalRoute(dataQuality, ["platform_admin"])).toBe(true);
    expect(canAccessTerminalRoute(dataQuality, ["researcher"])).toBe(false);
    expect(terminalRoutes.every((route) => canAccessTerminalRoute(route, ["platform_admin"]))).toBe(
      true,
    );
  });

  it("limits navigation and ready routes to daily research and account-only paper ledgers", () => {
    expect(
      terminalRoutes.filter((route) => route.status === "ready").map((route) => route.id),
    ).toEqual([
      "home",
      "market-overview",
      "instruments",
      "instrument-detail",
      "watchlists",
      "paper",
      "data-quality",
    ]);
    expect(terminalRoutes.filter((route) => route.navigation).map((route) => route.id)).toEqual([
      "home",
      "market-overview",
      "instruments",
      "watchlists",
      "paper",
      "data-quality",
    ]);
    expect(
      terminalRoutes
        .filter((route) => route.status === "planned")
        .every((route) => !route.navigation),
    ).toBe(true);
  });

  it("publishes data quality as an operations-only read surface", () => {
    const route = getTerminalRoute("data-quality");
    expect(route.path).toBe("/data-quality");
    expect(route.status).toBe("ready");
    expect(route.navigation).toBe(true);
    expect(route.permission).toBe("operations:read");
    expect(canAccessTerminalRoute(route, ["platform_admin"])).toBe(true);
    expect(canAccessTerminalRoute(route, ["viewer", "researcher", "paper_operator"])).toBe(false);
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
