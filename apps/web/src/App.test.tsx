import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import type * as ReactRouter from "react-router";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-router", async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ReactRouter;
  return {
    ...actual,
    BrowserRouter: ({ children }: { children: React.ReactNode }) => (
      <MemoryRouter initialEntries={["/data-quality"]}>{children}</MemoryRouter>
    ),
  };
});

vi.mock("./features/data-quality/data-quality-page", () => ({
  DataQualityPage: () => <div>DATA_QUALITY_PAGE_MARKER</div>,
}));

vi.mock("./components/ui/sonner", () => ({
  Toaster: () => null,
}));

import { App } from "./App";

describe("App routing", () => {
  it("serves the data-quality page at /data-quality", () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain("DATA_QUALITY_PAGE_MARKER");
  });
});
