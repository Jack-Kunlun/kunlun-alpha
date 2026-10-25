import { readPaperReconciliation } from "./paper-reconciliation";

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

/** Starts a browser-local download; it neither requests a new report nor writes server state. */
export function downloadPaperReconciliationExport(prepared: {
  filename: string;
  json: string;
}): void {
  let url: string | null = null;
  let anchor: HTMLAnchorElement | null = null;
  let started = false;
  try {
    url = URL.createObjectURL(
      new Blob([prepared.json], { type: "application/json;charset=utf-8" }),
    );
    anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = prepared.filename;
    anchor.hidden = true;
    document.body.append(anchor);
    anchor.click();
    started = true;
  } finally {
    anchor?.remove();
    if (url !== null) {
      const allocatedUrl = url;
      // The browser consumes the Blob asynchronously; keep it alive briefly after activation.
      if (started) setTimeout(() => URL.revokeObjectURL(allocatedUrl), 1000);
      else URL.revokeObjectURL(allocatedUrl);
    }
  }
}
