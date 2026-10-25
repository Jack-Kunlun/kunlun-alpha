import { z } from "zod";
import type { PaperReconciliationResult } from "@kunlun/shared-types";

const digest = z.string().regex(/^[0-9a-f]{64}$/);
const amount = z
  .string()
  .max(128)
  .regex(/^(?:0|[1-9]\d*)(?:\.\d+)?$/);
const diff = z
  .object({
    kind: z.enum(["CASH", "POSITION_QUANTITY", "POSITION_COST"]),
    instrumentId: z
      .string()
      .regex(/^\d{6}\.(SH|SZ|BJ)$/)
      .nullable(),
    expected: amount,
    observed: amount,
    difference: z
      .string()
      .max(129)
      .regex(/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/),
  })
  .strict();
const schema = z
  .object({
    schemaVersion: z.literal("paper-reconciliation-result-v1"),
    reconciliationId: digest,
    accountId: digest,
    asOf: z.iso.datetime({ offset: true }),
    status: z.enum(["MATCHED", "DRIFTED"]),
    expectedBookDigest: digest,
    observedBookDigest: digest,
    diffs: z.array(diff),
    duplicateFillCount: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    executionCapability: z.literal("PAPER_ONLY"),
    dataMeaning: z.literal("SIMULATION_BOOK_RECONCILIATION"),
  })
  .strict();

/** The control plane validates arithmetic; this display boundary also binds account and cutoff. */
export function readPaperReconciliation(
  value: unknown,
  accountId: string,
  basis: string,
): PaperReconciliationResult {
  const report = schema.parse(value);
  if (
    report.accountId !== accountId ||
    instant(report.asOf) < instant(basis) ||
    (report.status === "MATCHED"
      ? report.diffs.length !== 0 || report.expectedBookDigest !== report.observedBookDigest
      : report.diffs.length === 0 || report.expectedBookDigest === report.observedBookDigest)
  )
    throw new Error("核对报告与当前账本不一致");
  return report;
}
function instant(value: string): bigint {
  const match = /^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (match === null) throw new Error("核对时间无效");
  const milliseconds = Date.parse(`${match[1]}${match[3]}`);
  if (!Number.isFinite(milliseconds)) throw new Error("核对时间无效");
  return BigInt(milliseconds) * 1_000_000n + BigInt((match[2] ?? "").padEnd(9, "0"));
}
