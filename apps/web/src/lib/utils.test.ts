import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("joins truthy class names and drops falsy ones", () => {
    expect(cn("a", "b", null, undefined, false, 0)).toBe("a b");
  });

  it("merges Tailwind class conflicts keeping the last", () => {
    expect(cn("px-2", "p-4")).toBe("p-4");
  });

  it("returns an empty string when nothing is passed", () => {
    expect(cn()).toBe("");
  });
});
