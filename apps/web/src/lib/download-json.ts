/** Browser-local JSON download, with a short grace period for asynchronous Blob consumption. */
export function downloadJsonFile(prepared: { filename: string; json: string }): void {
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
      if (started) setTimeout(() => URL.revokeObjectURL(allocatedUrl), 1000);
      else URL.revokeObjectURL(allocatedUrl);
    }
  }
}
