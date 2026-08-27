import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const schema = JSON.parse(
  readFileSync("schemas/ranking/ranking-terminal-snapshot.json", "utf8"),
) as Record<string, unknown>;

describe("ranking terminal snapshot contract", () => {
  it("accepts only a versioned research snapshot as the production source", () => {
    const serialized = JSON.stringify(schema);
    expect(schema["title"]).toBe("RankingTerminalSnapshot");
    expect(serialized).toContain("VERSIONED_RESEARCH_SNAPSHOT");
    expect(serialized).not.toContain("SANITIZED_ACCEPTANCE_FIXTURE");
    expect(serialized).not.toMatch(/P6-N|Phase 6/);
  });

  it("requires point-in-time, algorithm, contribution and provenance fields", () => {
    expect(schema["required"]).toEqual(
      expect.arrayContaining([
        "snapshotId",
        "inputFingerprint",
        "asOf",
        "generatedAt",
        "spec",
        "rows",
      ]),
    );
    const serialized = JSON.stringify(schema);
    expect(serialized).toContain("algorithmVersion");
    expect(serialized).toContain("availableTime");
    expect(serialized).toContain("source");
  });
});
