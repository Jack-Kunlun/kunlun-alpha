import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const load = (name: string): Record<string, unknown> =>
  JSON.parse(readFileSync(`schemas/paper/${name}.json`, "utf8")) as Record<string, unknown>;

describe("paper terminal contracts", () => {
  it("keeps the workspace simulation-only and explicitly volatile", () => {
    const schema = load("paper-terminal-workspace");
    const serialized = JSON.stringify(schema);
    expect(schema["title"]).toBe("PaperTerminalWorkspace");
    expect(serialized).toContain("SIMULATION_ONLY_NO_BROKER_PATH");
    expect(serialized).toContain("VOLATILE_IN_MEMORY");
    expect(serialized).not.toMatch(/P6-N|Phase 6|QMT/);
  });

  it("defines bounded idempotent create-account and simulation commands", () => {
    const create = load("paper-terminal-create-account");
    const simulation = load("paper-terminal-simulation");
    expect(create["required"]).toEqual(
      expect.arrayContaining(["clientRequestId", "initialCapital"]),
    );
    expect(simulation["required"]).toEqual(
      expect.arrayContaining(["clientRequestId", "instrumentId", "price", "confidence"]),
    );
    expect(JSON.stringify(simulation)).not.toContain("broker");
  });
});
