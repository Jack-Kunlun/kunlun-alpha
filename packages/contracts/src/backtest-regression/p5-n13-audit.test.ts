import { describe, expect, it } from "vitest";

import { canonicalJson, parseCanonicalJson } from "./index";

describe("P5-N13 cross-runtime canonicalization", () => {
  it.each(["\ue000", "\u{10000}"])("rejects non-ASCII object key %s", (key) => {
    expect(() => canonicalJson({ outer: { [key]: 1 } })).toThrow();

    const payload = `${JSON.stringify({ outer: { [key]: 1 } })}\n`;
    expect(() => parseCanonicalJson(payload)).toThrow();
  });
});
