import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api-client";
import { rankingTerminalResult } from "./use-ranking-terminal";

describe("rankingTerminalResult", () => {
  it("maps an unpublished repository to an explicit empty state", () => {
    expect(
      rankingTerminalResult({ status: "error", data: null, error: new ApiError("missing", 404) }),
    ).toEqual({ state: "empty", message: "当前没有已发布的 Ranking 快照" });
  });

  it("keeps forbidden and source failures distinct", () => {
    expect(
      rankingTerminalResult({
        status: "forbidden",
        data: null,
        error: new ApiError("denied", 403),
      }),
    ).toEqual({ state: "forbidden", message: "当前身份无权读取排名快照" });
    expect(
      rankingTerminalResult({ status: "error", data: null, error: new ApiError("down", 503) }),
    ).toEqual({ state: "error", message: "down" });
  });
});
