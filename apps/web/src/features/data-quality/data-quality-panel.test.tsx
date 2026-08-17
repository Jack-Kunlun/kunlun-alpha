import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DataQualityPanel } from "./data-quality-panel";
import type { DataQualityRecord } from "./types";

const records: DataQualityRecord[] = [
  {
    id: "fund-conflict-aaa",
    kind: "SOURCE_CONFLICT",
    unifiedCode: "600519.SH",
    date: "2026-08-13",
    source: "provider-a",
    detail: "多来源观测不一致，未选择权威值",
    createdAt: "2026-08-13T09:30:00.000Z",
    availableAt: "2026-08-13T09:30:00.000Z",
    schemaVersion: "fund-v1",
  },
];

describe("DataQualityPanel", () => {
  it("renders every record detail including version and reason", () => {
    const html = renderToStaticMarkup(<DataQualityPanel records={records} />);
    expect(html).toContain("SOURCE_CONFLICT");
    expect(html).toContain("600519.SH");
    expect(html).toContain("多来源观测不一致，未选择权威值");
    expect(html).toContain("fund-v1");
  });

  it("links evidence only through the safe internal endpoint", () => {
    const html = renderToStaticMarkup(<DataQualityPanel records={records} />);
    expect(html).toContain('href="/v1/data-quality/fund-conflict-aaa/evidence"');
    expect(html).not.toContain("raw://");
    expect(html).not.toContain("s3://");
    expect(html).not.toContain("raw_object");
  });
});
