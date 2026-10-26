import { readPaperReconciliation } from "./paper-reconciliation";
export { downloadJsonFile as downloadPaperReconciliationExport } from "@/lib/download-json";

/** Preserve the existing report contract verbatim, including decimal text and its original cutoff. */
export function preparePaperReconciliationExport(
  value: unknown,
  accountId: string,
  basis: string,
): {
  filename: string;
  json: string;
} {
  const report = readPaperReconciliation(value, accountId, basis);
  const time = new Date(report.asOf).toISOString().slice(0, 19).replaceAll(/[-:]/g, "") + "Z";
  return {
    filename: `paper-reconciliation-${time}-${report.reconciliationId.slice(0, 12)}.json`,
    json: `${JSON.stringify(report, null, 2)}\n`,
  };
}
