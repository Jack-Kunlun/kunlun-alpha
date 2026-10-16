import { mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { MarketDataStatusReader } from "./market-data-status.reader";

const symbols = ["000001.SZ", "600519.SH"];
const now = new Date("2026-10-16T10:30:00.000Z");
const success = {
  schemaVersion: "market-data-sync-status-v1",
  status: "SUCCEEDED",
  provider: "akshare",
  symbols,
  lastAttemptAt: "2026-10-16T10:20:00.000Z",
  lastFinishedAt: "2026-10-16T10:20:05.000Z",
  lastSuccessAt: "2026-10-16T10:20:05.000Z",
  lastSuccessResult: { requests: 2, receivedBars: 100, writtenBars: 100, dailyRefreshed: true },
  errorCode: null,
};
const roots: string[] = [];

async function reader(payload?: unknown) {
  const root = await mkdtemp(join(tmpdir(), "kunlun-sync-status-"));
  roots.push(root);
  if (payload !== undefined) {
    await writeFile(join(root, "market-data-sync-status.json"), JSON.stringify(payload));
  }
  return { root, service: new MarketDataStatusReader(root, symbols, "akshare", () => now) };
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe("MarketDataStatusReader", () => {
  it("reports unknown before any recorded task, rather than inventing a success", async () => {
    const { service } = await reader();
    expect(await service.read()).toMatchObject({
      status: "UNKNOWN",
      errorCode: "NO_RUN",
      lastSuccessAt: null,
    });
  });

  it("returns the actual task timestamps and counts without refreshing them on read", async () => {
    const { service } = await reader(success);
    expect(await service.read()).toEqual(success);
    expect(await service.read()).toEqual(success);
  });

  it("preserves the preceding successful result when the latest attempt failed", async () => {
    const failed = {
      ...success,
      status: "FAILED",
      lastAttemptAt: "2026-10-16T10:25:00.000Z",
      lastFinishedAt: "2026-10-16T10:25:02.000Z",
      errorCode: "SOURCE_ERROR",
    };
    const { service } = await reader(failed);
    expect(await service.read()).toEqual(failed);
  });

  it("retains zero counters for a successful no-op task", async () => {
    const noOp = {
      ...success,
      lastSuccessResult: { requests: 0, receivedBars: 0, writtenBars: 0, dailyRefreshed: false },
    };
    const { service } = await reader(noOp);
    expect(await service.read()).toEqual(noOp);
  });

  it("shows a recent unfinished attempt while retaining the preceding success", async () => {
    const running = {
      ...success,
      status: "RUNNING",
      lastAttemptAt: "2026-10-16T10:25:00.000Z",
      lastFinishedAt: null,
    };
    const { service } = await reader(running);
    expect(await service.read()).toEqual(running);
  });

  it("does not present another configured sample set as this sample's success", async () => {
    const { service } = await reader({ ...success, symbols: ["600000.SH"] });
    expect(await service.read()).toMatchObject({
      status: "UNKNOWN",
      errorCode: "SCOPE_MISMATCH",
      lastSuccessAt: null,
    });
  });

  it.each([
    { ...success, token: "fixture-secret" },
    { ...success, lastSuccessAt: "not-a-time" },
    {
      ...success,
      lastAttemptAt: "2026-10-15T24:00:00Z",
      lastFinishedAt: "2026-10-15T24:00:00Z",
      lastSuccessAt: "2026-10-15T24:00:00Z",
    },
    { ...success, lastFinishedAt: "2026-10-16T10:19:00.000Z" },
    {
      ...success,
      lastSuccessResult: { requests: 1, receivedBars: 1, writtenBars: -1, dailyRefreshed: true },
    },
    { ...success, errorCode: "postgresql://fixture-secret.invalid" },
  ])("rejects malformed or unsafe records without echoing their content", async (payload) => {
    const { service } = await reader(payload);
    const result = await service.read();
    expect(result).toMatchObject({
      status: "UNKNOWN",
      errorCode: "INVALID_STATUS",
      lastSuccessAt: null,
    });
    expect(JSON.stringify(result)).not.toContain("fixture-secret");
  });

  it("marks an old unfinished attempt as unconfirmed, preserving previous success", async () => {
    const running = {
      ...success,
      status: "RUNNING",
      lastAttemptAt: "2026-10-16T10:25:00.000Z",
      lastFinishedAt: null,
    };
    const { root } = await reader(running);
    const service = new MarketDataStatusReader(
      root,
      symbols,
      "akshare",
      () => new Date("2026-10-16T11:00:00Z"),
    );
    expect(await service.read()).toMatchObject({
      status: "UNKNOWN",
      errorCode: "RUN_STATUS_EXPIRED",
      lastSuccessAt: success.lastSuccessAt,
    });
  });

  it("does not follow a status-file symlink", async () => {
    const { root, service } = await reader();
    const target = join(root, "private.json");
    await writeFile(target, JSON.stringify(success));
    await symlink(target, join(root, "market-data-sync-status.json"));
    expect(await service.read()).toMatchObject({ status: "UNKNOWN", errorCode: "INVALID_STATUS" });
  });

  it("bounds file reads", async () => {
    const { root, service } = await reader();
    await writeFile(join(root, "market-data-sync-status.json"), "x".repeat(65_537));
    expect(await service.read()).toMatchObject({ status: "UNKNOWN", errorCode: "INVALID_STATUS" });
  });
});
