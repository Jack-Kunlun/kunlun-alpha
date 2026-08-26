import "reflect-metadata";

import { PATH_METADATA } from "@nestjs/common/constants";
import { describe, expect, it } from "vitest";
import { LimitPoolController } from "./limit-pool.controller";

describe("limit-pool API route prefix", () => {
  it("leaves /api/v1 ownership to the application global prefix", () => {
    expect(Reflect.getMetadata(PATH_METADATA, LimitPoolController)).toBe("limit-pool");
  });
});
