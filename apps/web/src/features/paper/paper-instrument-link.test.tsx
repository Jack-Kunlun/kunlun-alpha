import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { currentInstrumentDailyHref } from "@/features/instrument/instrument-daily-link";
import { parseTerminalFilters } from "@/app/filter-context";
import { PaperInstrumentLink } from "./paper-instrument-link";

function html(instrumentId: string) {
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={["/paper?asOf=2026-01-01T00:00:00Z&instrument=000001.SZ"]}>
      <PaperInstrumentLink instrumentId={instrumentId} />
    </MemoryRouter>,
  );
}
describe("paper to current daily research", () => {
  it.each(["600519.SH", "000001.SZ", "920000.BJ"])(
    "links %s without inherited historical or symbol filters",
    (code) => {
      const href = currentInstrumentDailyHref(code)!;
      expect(href).toBe(`/instruments/${code}`);
      expect(parseTerminalFilters(new URL(href, "http://example.test").search).value).toMatchObject(
        { asOf: null, instrumentIds: [] },
      );
      const rendered = html(code);
      expect(rendered).toContain(`href="${href}"`);
      expect(rendered).toContain(`查看 ${code} 当前已入库日线`);
      expect(rendered).toContain("不重算模拟价格或账本");
      expect(rendered).toContain("cursor-pointer");
      expect(rendered).toContain("focus-visible:ring");
    },
  );
  it.each([
    "600519.sh",
    "../600519.SH",
    "600519.SH?asOf=2026-01-01",
    "https://example.test",
    "00700.HK",
    "",
  ])("does not create an actionable destination for invalid input %s", (code) => {
    expect(currentInstrumentDailyHref(code)).toBeNull();
    expect(html(code)).not.toContain("href=");
  });
});
