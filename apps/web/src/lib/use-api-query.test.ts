import { describe, expect, it, vi } from "vitest";
import { scheduleQueryRefresh } from "./use-api-query";

describe("query refresh scheduler", () => {
  it("advances current polling and cancels the interval", () => {
    vi.useFakeTimers();
    const callback = vi.fn();
    const scheduler = {
      setInterval: (next: () => void, intervalMs: number) =>
        globalThis.setInterval(next, intervalMs) as unknown as number,
      clearInterval: (intervalId: number) =>
        globalThis.clearInterval(
          intervalId as unknown as ReturnType<typeof globalThis.setInterval>,
        ),
    };
    const cancel = scheduleQueryRefresh(callback, 30_000, scheduler);
    vi.advanceTimersByTime(90_000);
    expect(callback).toHaveBeenCalledTimes(3);
    cancel();
    vi.advanceTimersByTime(30_000);
    expect(callback).toHaveBeenCalledTimes(3);
    vi.useRealTimers();
  });
});
