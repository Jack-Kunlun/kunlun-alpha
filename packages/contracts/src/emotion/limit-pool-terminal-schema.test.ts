import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const schemaPath = new URL(
  "../../schemas/emotion/terminal-limit-pool-snapshot.json",
  import.meta.url,
);

describe("limit-pool terminal contract source", () => {
  it("defines the versioned terminal snapshot and every public nested type", () => {
    const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as {
      title?: string;
      properties?: Record<string, unknown>;
      required?: string[];
      $defs?: Record<string, unknown>;
    };

    expect(schema.title).toBe("LimitPoolTerminalSnapshot");
    expect(schema.properties).toHaveProperty("schemaVersion");
    expect(schema.required).toContain("dataMeaning");
    expect(schema.$defs).toEqual(
      expect.objectContaining({
        LimitPoolTerminalFreshnessStatus: expect.any(Object),
        LimitPoolTerminalCompleteness: expect.any(Object),
        LimitPoolSide: expect.any(Object),
        LimitPoolState: expect.any(Object),
        LimitPoolListingBoard: expect.any(Object),
        PositiveDecimalString: expect.objectContaining({
          pattern: "^(?:0\\.\\d*[1-9]\\d*|[1-9]\\d*(?:\\.\\d+)?)$",
        }),
        LimitPoolTerminalEntry: expect.any(Object),
        LimitPoolLadderLevel: expect.any(Object),
      }),
    );
    const entry = schema.$defs?.LimitPoolTerminalEntry as {
      properties?: Record<string, { $ref?: string }>;
    };
    expect(entry.properties?.priceCny?.$ref).toBe("#/$defs/PositiveDecimalString");
    expect(entry.properties?.previousCloseCny?.$ref).toBe("#/$defs/PositiveDecimalString");
  });
});
