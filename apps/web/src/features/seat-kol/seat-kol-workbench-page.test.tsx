import { renderToStaticMarkup } from "react-dom/server";
import type { SeatKolWorkbenchSnapshot } from "@kunlun/shared-types";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LOCAL_PREVIEW_SEAT_KOL_SNAPSHOT } from "../../__fixtures__/seat-kol-snapshot";
import { SeatKolWorkbenchPage } from "./seat-kol-workbench-page";
import { useSeatKolWorkbench } from "./use-seat-kol-workbench";

vi.mock("./use-seat-kol-workbench", () => ({ useSeatKolWorkbench: vi.fn() }));
const mocked = vi.mocked(useSeatKolWorkbench);
const snapshot = LOCAL_PREVIEW_SEAT_KOL_SNAPSHOT as SeatKolWorkbenchSnapshot;

describe("SeatKolWorkbenchPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders loading, empty, error and forbidden states", () => {
    mocked.mockReturnValue({ status: "loading", data: null, error: null });
    expect(renderToStaticMarkup(<SeatKolWorkbenchPage />)).toContain("正在装载审计链");
    mocked.mockReturnValue({ status: "empty", data: [], error: null });
    expect(renderToStaticMarkup(<SeatKolWorkbenchPage />)).toContain("暂无符合条件的数据");
    mocked.mockReturnValue({ status: "error", data: null, error: new Error("offline") });
    expect(renderToStaticMarkup(<SeatKolWorkbenchPage />)).toContain("工作台数据加载失败");
    mocked.mockReturnValue({ status: "forbidden", data: null, error: new Error("denied") });
    expect(renderToStaticMarkup(<SeatKolWorkbenchPage />)).toContain("无权访问席位与 KOL 工作台");
  });

  it("renders profiles, evidence, metrics, cooccurrence and review warning", () => {
    mocked.mockReturnValue({ status: "success", data: [snapshot], error: null });
    const html = renderToStaticMarkup(<SeatKolWorkbenchPage />);
    for (const text of [
      "席位 × KOL 情报台",
      "华东示例营业部",
      "公开内容样例 KOL",
      "seat-performance-v1",
      "样本</dt><dd>42",
      "数据截止",
      "共现观察",
      "Claim 审核队列",
      "不是券商成交、订单、持仓或账户事实",
      "本地脱敏预览",
    ])
      expect(html).toContain(text);
  });

  it("associates every workbench filter label with a control", () => {
    mocked.mockReturnValue({ status: "success", data: [snapshot], error: null });
    const html = renderToStaticMarkup(<SeatKolWorkbenchPage />);
    for (const id of ["seat-kol-query", "seat-kol-entity", "seat-kol-review", "seat-kol-as-of"]) {
      expect(html).toContain(`for="${id}"`);
    }
  });
});
