import { BadRequestException, UnauthorizedException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { parseWatchlistImport } from "./personal-watchlist.validation";
import { PersonalWatchlistController } from "./personal-watchlist.controller";
import type { AuthenticatedRequest } from "../auth/auth.request";

const command = () => ({
  schemaVersion: "personal-watchlist-import-v1",
  clientRequestId: "00000000-0000-4000-8000-000000000001",
  items: [{ code: "600000.SH", name: "示例" }],
});
describe("personal watchlist boundary", () => {
  it("validates the entire command and rejects owner injection or malformed items", () => {
    expect(parseWatchlistImport(command()).items).toHaveLength(1);
    for (const body of [
      { ...command(), ownerId: "other" },
      { ...command(), items: [{ code: "HK:1", name: "X" }] },
      { ...command(), items: [{ code: "600000.SH", name: "<X>" }] },
      { ...command(), items: [] },
      { ...command(), clientRequestId: "bad" },
    ]) {
      expect(() => parseWatchlistImport(body)).toThrow(BadRequestException);
    }
  });
  it("preserves first duplicate name and supports external observation codes", () => {
    const parsed = parseWatchlistImport({
      ...command(),
      items: [
        { code: "600000.SH", name: "first" },
        { code: "600000.SH", name: "second" },
        { code: "SGE:AU99.99", name: "Au99.99" },
      ],
    });
    expect(parsed.items.map((x) => x.name)).toEqual(["first", "Au99.99"]);
  });
  it("requires an authenticated owner before accessing persistence", () => {
    const controller = new PersonalWatchlistController({} as never);
    expect(() => controller.list({} as AuthenticatedRequest)).toThrow(UnauthorizedException);
    expect(() => controller.importItems({} as AuthenticatedRequest, command())).toThrow(
      UnauthorizedException,
    );
  });
});

it("uses the global version prefix and forbids caching private responses", () => {
  expect(Reflect.getMetadata("path", PersonalWatchlistController)).toBe("personal-watchlist");
  for (const handler of [
    PersonalWatchlistController.prototype.list,
    PersonalWatchlistController.prototype.importItems,
  ]) {
    expect(Reflect.getMetadata("__headers__", handler)).toContainEqual({
      name: "Cache-Control",
      value: "no-store",
    });
  }
});
