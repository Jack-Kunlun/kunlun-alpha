import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DataQualityPanel, type DataQualityRecord } from "./data-quality-panel";

const records: DataQualityRecord[] = [
  {
    id: "q1",
    kind: "NEGATIVE_PRICE",
    date: "2026-08-13",
    source: "provider-x",
    unifiedCode: "600000.SH",
    detail: "close must be >= 0",
    evidenceLink: "raw://objects/abc123",
  },
  {
    id: "q2",
    kind: "MISSING_DATE",
    date: "2026-08-14",
    source: "provider-y",
    unifiedCode: null,
    detail: "no calendar data",
    evidenceLink: "raw://objects/def456",
  },
];

describe("DataQualityPanel", () => {
  it("renders every record detail, not only totals", () => {
    const html = renderToStaticMarkup(<DataQualityPanel records={records} />);
    expect(html).toContain("NEGATIVE_PRICE");
    expect(html).toContain("MISSING_DATE");
    expect(html).toContain("close must be &gt;= 0");
    expect(html).toContain("600000.SH");
  });

  it("links each record to its raw evidence", () => {
    const html = renderToStaticMarkup(<DataQualityPanel records={records} />);
    expect(html).toContain('href="raw://objects/abc123"');
    expect(html).toContain('href="raw://objects/def456"');
  });

  it("renders an empty state when there are no records", () => {
    const html = renderToStaticMarkup(<DataQualityPanel records={[]} />);
    expect(html).toContain("暂无质量问题");
  });
});
