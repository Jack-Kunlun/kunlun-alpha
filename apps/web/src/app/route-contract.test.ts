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
      ]),
    );
  });

  it("applies the role matrix without exposing operations or paper routes to viewers", () => {
    const viewerRoutes = visibleTerminalRoutes(["viewer"]);
    expect(viewerRoutes.map((route) => route.id)).toContain("precious-metals");
    expect(viewerRoutes.map((route) => route.id)).not.toContain("paper");
    expect(viewerRoutes.map((route) => route.id)).not.toContain("data-quality");
    expect(canAccessTerminalRoute(getTerminalRoute("paper"), ["paper_operator"])).toBe(true);
    expect(terminalRoutes.every((route) => canAccessTerminalRoute(route, ["platform_admin"]))).toBe(
      true,
    );
  });

  it("marks both instrument entry and deep-link routes ready", () => {
    expect(getTerminalRoute("instruments").status).toBe("ready");
    expect(getTerminalRoute("instrument-detail").status).toBe("ready");
  });
});
