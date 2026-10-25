import type { PaperBookDiff, PaperReconciliationResult } from "@kunlun/shared-types";
import { paperPreviewValidation as p } from "./paper-preview-response";

/** Validate the existing contract plus the arithmetic/status invariants of this zero-tolerance API. */
export function parsePaperReconciliationResponse(value: unknown): PaperReconciliationResult {
  const row = p.record(value, [
    "schemaVersion",
    "reconciliationId",
    "accountId",
    "asOf",
    "status",
    "expectedBookDigest",
    "observedBookDigest",
    "diffs",
    "duplicateFillCount",
    "executionCapability",
    "dataMeaning",
  ]);
  if (
    row.schemaVersion !== "paper-reconciliation-result-v1" ||
    row.executionCapability !== "PAPER_ONLY" ||
    row.dataMeaning !== "SIMULATION_BOOK_RECONCILIATION" ||
    !["MATCHED", "DRIFTED"].includes(p.text(row.status)) ||
    !Array.isArray(row.diffs)
  )
    fail();
  const expectedBookDigest = p.digest(row.expectedBookDigest),
    observedBookDigest = p.digest(row.observedBookDigest);
  const seen = new Set<string>();
  const diffs: PaperBookDiff[] = row.diffs.map((value: unknown) => {
    const d = p.record(value, ["kind", "instrumentId", "expected", "observed", "difference"]);
    if (d.kind !== "CASH" && d.kind !== "POSITION_QUANTITY" && d.kind !== "POSITION_COST") fail();
    if (
      d.kind === "CASH"
        ? d.instrumentId !== null
        : typeof d.instrumentId !== "string" || !/^\d{6}\.(SH|SZ|BJ)$/.test(d.instrumentId)
    )
      fail();
    const key = `${d.kind}:${String(d.instrumentId)}`;
    if (seen.has(key)) fail();
    seen.add(key);
    const expected = p.decimal(d.expected),
      observed = p.decimal(d.observed),
      difference = p.text(d.difference);
    if (difference.length > 129 || !/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(difference)) fail();
    if (
      d.kind === "POSITION_QUANTITY" &&
      ![expected, observed, difference.replace(/^-/, "")].every((s) => /^\d+$/.test(s))
    )
      fail();
    const scale = Math.max(
      ...[expected, observed, difference].map((s) => s.split(".")[1]?.length ?? 0),
    );
    const e = scaled(expected, scale),
      o = scaled(observed, scale),
      delta = scaled(difference, scale);
    if (delta === 0n || o - e !== delta) fail();
    return {
      kind: d.kind,
      instrumentId: d.instrumentId as string | null,
      expected,
      observed,
      difference,
    };
  });
  if (
    row.status === "MATCHED"
      ? diffs.length !== 0 || expectedBookDigest !== observedBookDigest
      : diffs.length === 0 || expectedBookDigest === observedBookDigest
  )
    fail();
  return {
    schemaVersion: "paper-reconciliation-result-v1",
    reconciliationId: p.digest(row.reconciliationId),
    accountId: p.digest(row.accountId),
    asOf: p.timestamp(row.asOf),
    status: row.status as "MATCHED" | "DRIFTED",
    expectedBookDigest,
    observedBookDigest,
    diffs,
    duplicateFillCount: p.integer(row.duplicateFillCount),
    executionCapability: "PAPER_ONLY",
    dataMeaning: "SIMULATION_BOOK_RECONCILIATION",
  };
}
function scaled(value: string, scale: number): bigint {
  const negative = value.startsWith("-");
  const [whole = "0", fraction = ""] = (negative ? value.slice(1) : value).split(".");
  return BigInt(whole + fraction.padEnd(scale, "0")) * (negative ? -1n : 1n);
}
function fail(): never {
  throw new Error("quant-engine returned an invalid paper reconciliation");
}
