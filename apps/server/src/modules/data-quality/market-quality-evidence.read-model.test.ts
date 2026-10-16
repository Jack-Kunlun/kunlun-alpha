import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, realpath, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { promisify } from "node:util";
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import type {
  MarketQualityEvidenceRecord,
  MarketQualityEvidenceSnapshot,
} from "@kunlun/shared-types";
import {
  FileMarketQualityEvidenceSnapshotReader,
  MarketQualityEvidenceReadError,
} from "./market-quality-evidence.reader";
import {
  FileMarketQualityEvidenceReadModel,
  MarketQualityEvidenceNotFoundError,
} from "./market-quality-evidence.read-model";

const record: MarketQualityEvidenceRecord = {
  evidenceId: `mqe-${"a".repeat(64)}`,
  source: "akshare-tencent",
  unifiedCode: "600519.SH",
  interval: "DAILY",
  requestedStart: "2026-08-01",
  requestedEnd: "2026-08-31",
  status: "REJECTED",
  reasonCode: "BAR_QUALITY_REJECTED",
  captureAvailableAt: "2026-09-01T01:00:00.000Z",
  qualityRecordedAt: "2026-09-01T01:01:00.000Z",
  rejectedRecordCount: 1,
  qualityEventCount: 1,
  filteredRecordCount: 0,
  qualityEvents: [{ kind: "NEGATIVE_PRICE", unifiedCode: "600519.SH", timestamp: null }],
  filteredRecords: [],
};

const snapshot: MarketQualityEvidenceSnapshot = {
  schemaVersion: "market-quality-snapshot-v1",
  publishedAt: "2026-09-01T01:02:00.000001Z",
  records: [record],
};

const execFileAsync = promisify(execFile);

async function installSnapshot(root: string, value: unknown): Promise<string> {
  const bytes = Buffer.from(JSON.stringify(value), "utf8");
  const id = createHash("sha256").update(bytes).digest("hex");
  await writeFile(join(root, "snapshots", `${id}.json`), bytes);
  await writeFile(
    join(root, "current.json"),
    JSON.stringify({ schemaVersion: "market-quality-current-v1", snapshotId: id }),
  );
  return id;
}

describe("FileMarketQualityEvidenceSnapshotReader", () => {
  let root: string;
  let snapshotId: string;

  beforeEach(async () => {
    root = await mkdtemp(join(await realpath(tmpdir()), "kunlun-market-quality-reader-"));
    await mkdir(join(root, "snapshots"));
    snapshotId = await installSnapshot(root, snapshot);
  });

  afterEach(async () => {
    await rm(root, { recursive: true, force: true });
  });

  it("reads an immutable digest-addressed snapshot through the current pointer", async () => {
    const reader = new FileMarketQualityEvidenceSnapshotReader(
      root,
      () => new Date("2026-09-01T02:00:00.000Z"),
    );
    await expect(reader.readCurrent()).resolves.toMatchObject({
      snapshotId,
      snapshot: { records: [record] },
    });
  });

  it("preserves microsecond causal ordering and allows future event timestamps", async () => {
    const futureEventSnapshot: MarketQualityEvidenceSnapshot = {
      ...snapshot,
      records: [
        {
          ...record,
          qualityEvents: [
            {
              kind: "NEGATIVE_PRICE",
              unifiedCode: "600519.SH",
              timestamp: "2099-01-01T00:00:00.123456Z",
            },
          ],
        },
      ],
    };
    const id = await installSnapshot(root, futureEventSnapshot);
    const reader = new FileMarketQualityEvidenceSnapshotReader(
      root,
      () => new Date("2026-09-01T02:00:00.000Z"),
    );
    await expect(reader.readCurrent()).resolves.toMatchObject({ snapshotId: id });

    const invalidOrder: MarketQualityEvidenceSnapshot = {
      ...snapshot,
      records: [{ ...record, qualityRecordedAt: "2026-09-01T01:02:00.000002Z" }],
    };
    await installSnapshot(root, invalidOrder);
    await expect(reader.readCurrent()).rejects.toBeInstanceOf(MarketQualityEvidenceReadError);
  });

  it("validates record, event, and filtered-record allowlists after digest verification", async () => {
    const unknownRecord = { ...record, secretSentinel: "record" };
    await installSnapshot(root, { ...snapshot, records: [unknownRecord] });
    const reader = new FileMarketQualityEvidenceSnapshotReader(
      root,
      () => new Date("2026-09-01T02:00:00.000Z"),
    );
    await expect(reader.readCurrent()).rejects.toBeInstanceOf(MarketQualityEvidenceReadError);

    const unknownEvent = {
      ...record,
      qualityEvents: [{ ...record.qualityEvents[0], secretSentinel: "event" }],
    };
    await installSnapshot(root, { ...snapshot, records: [unknownEvent] });
    await expect(reader.readCurrent()).rejects.toBeInstanceOf(MarketQualityEvidenceReadError);

    const filteredRecord = {
      ...record,
      source: "akshare-sina" as const,
      status: "FILTERED" as const,
      reasonCode: "SINA_OVERFETCH_OUTSIDE_REQUEST" as const,
      rejectedRecordCount: 0,
      qualityEventCount: 0,
      filteredRecordCount: 1,
      qualityEvents: [],
      filteredRecords: [
        {
          rawRowIndex: 9_007_199_254_740_991,
          timestamp: "2026-09-01T00:00:00.000000Z",
          requestedStart: record.requestedStart,
          requestedEnd: record.requestedEnd,
          reasonCode: "SINA_OVERFETCH_OUTSIDE_REQUEST" as const,
        },
      ],
    };
    const filteredId = await installSnapshot(root, {
      ...snapshot,
      records: [{ ...filteredRecord, evidenceId: `mqe-${"b".repeat(64)}` }],
    });
    await expect(reader.readCurrent()).resolves.toMatchObject({ snapshotId: filteredId });

    await installSnapshot(root, {
      ...snapshot,
      records: [
        {
          ...filteredRecord,
          evidenceId: `mqe-${"b".repeat(64)}`,
          filteredRecords: [{ ...filteredRecord.filteredRecords[0], reasonCode: "unexpected" }],
        },
      ],
    });
    await expect(reader.readCurrent()).rejects.toBeInstanceOf(MarketQualityEvidenceReadError);

    await installSnapshot(root, {
      ...snapshot,
      records: [
        {
          ...filteredRecord,
          evidenceId: `mqe-${"b".repeat(64)}`,
          filteredRecords: [
            ...filteredRecord.filteredRecords,
            { ...filteredRecord.filteredRecords[0] },
          ],
          filteredRecordCount: 2,
        },
      ],
    });
    await expect(reader.readCurrent()).rejects.toBeInstanceOf(MarketQualityEvidenceReadError);
  });

  it("fails closed for a digest mismatch and unknown fields", async () => {
    await writeFile(
      join(root, "snapshots", `${snapshotId}.json`),
      JSON.stringify({ ...snapshot, unexpected: "secret-sentinel" }),
    );
    const reader = new FileMarketQualityEvidenceSnapshotReader(root);
    await expect(reader.readCurrent()).rejects.toBeInstanceOf(MarketQualityEvidenceReadError);
    await expect(reader.readCurrent()).rejects.not.toThrow("secret-sentinel");
  });

  it("rejects oversized files, static symlinks, and FIFOs without blocking", async () => {
    const reader = new FileMarketQualityEvidenceSnapshotReader(root);
    const oversized = Buffer.alloc(8 * 1024 * 1024 + 1, 0x20);
    const oversizedId = createHash("sha256").update(oversized).digest("hex");
    await writeFile(join(root, "snapshots", `${oversizedId}.json`), oversized);
    await writeFile(
      join(root, "current.json"),
      JSON.stringify({ schemaVersion: "market-quality-current-v1", snapshotId: oversizedId }),
    );
    await expect(reader.readCurrent()).rejects.toBeInstanceOf(MarketQualityEvidenceReadError);

    const target = join(root, "snapshots", `${snapshotId}.json`);
    const copy = join(root, "snapshot-copy.json");
    await writeFile(copy, Buffer.from(JSON.stringify(snapshot), "utf8"));
    await rm(target);
    await symlink(copy, target);
    await writeFile(
      join(root, "current.json"),
      JSON.stringify({ schemaVersion: "market-quality-current-v1", snapshotId }),
    );
    await expect(reader.readCurrent()).rejects.toBeInstanceOf(MarketQualityEvidenceReadError);

    if (process.platform !== "win32") {
      await rm(target);
      await execFileAsync("mkfifo", [target]);
      await expect(reader.readCurrent()).rejects.toBeInstanceOf(MarketQualityEvidenceReadError);
    }
  });

  it("rejects a symlinked configured root on direct snapshot reads", async () => {
    const linkedRoot = join(dirname(root), `${basename(root)}-link`);
    await symlink(root, linkedRoot);
    try {
      const reader = new FileMarketQualityEvidenceSnapshotReader(linkedRoot);
      await expect(reader.readSnapshot(snapshotId)).rejects.toBeInstanceOf(
        MarketQualityEvidenceReadError,
      );
    } finally {
      await rm(linkedRoot, { force: true });
    }
  });

  it("pins pagination to one snapshot and filters by request-window intersection", async () => {
    const reader = new FileMarketQualityEvidenceSnapshotReader(
      root,
      () => new Date("2026-09-01T02:00:00.000Z"),
    );
    const model = new FileMarketQualityEvidenceReadModel(reader);
    await expect(
      model.list({
        start: "2026-08-31",
        end: "2026-09-01",
        limit: 1,
        offset: 0,
      }),
    ).resolves.toMatchObject({
      snapshotId,
      snapshotRecordCount: 1,
      matchingRecordCount: 1,
      hasMore: false,
      records: [record],
    });
    await expect(model.detail(record.evidenceId, snapshotId)).resolves.toMatchObject({
      snapshotId,
      record,
    });
    await expect(model.detail(`mqe-${"b".repeat(64)}`, snapshotId)).rejects.toBeInstanceOf(
      MarketQualityEvidenceNotFoundError,
    );
  });

  it("keeps page ordering and pagination pinned to the selected snapshot", async () => {
    const second: MarketQualityEvidenceRecord = {
      ...record,
      evidenceId: `mqe-${"b".repeat(64)}`,
      source: "akshare-eastmoney",
      qualityEvents: [],
      qualityEventCount: 0,
    };
    const twoRecordSnapshot: MarketQualityEvidenceSnapshot = {
      ...snapshot,
      records: [record, second],
    };
    const id = await installSnapshot(root, twoRecordSnapshot);
    const reader = new FileMarketQualityEvidenceSnapshotReader(
      root,
      () => new Date("2026-09-01T02:00:00.000Z"),
    );
    const model = new FileMarketQualityEvidenceReadModel(reader);
    await expect(model.list({ limit: 1, offset: 0, snapshotId: id })).resolves.toMatchObject({
      snapshotId: id,
      matchingRecordCount: 2,
      hasMore: true,
      records: [record],
    });
    await expect(model.list({ limit: 1, offset: 1, snapshotId: id })).resolves.toMatchObject({
      snapshotId: id,
      matchingRecordCount: 2,
      hasMore: false,
      records: [second],
    });
  });
});
