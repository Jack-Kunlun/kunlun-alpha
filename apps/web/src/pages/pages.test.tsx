import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { Home } from "./Home";
import { NotFound } from "./NotFound";

describe("terminal page states", () => {
  it("renders the frozen 1.0 daily research scope", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    );
    expect(html).toContain("查看沪深日线行情与自选提醒");
    expect(html).toContain("日线研究终端");
    expect(html).toContain('href="/watchlists"');
    expect(html).not.toContain('href="/paper"');
    expect(html).not.toContain("模拟执行");
  });

  it("renders a navigable 404 state", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <NotFound />
      </MemoryRouter>,
    );
    expect(html).toContain("404");
    expect(html).toContain('href="/"');
  });

  it("derives an explicit error state", () => {
    const error = new Error("boom");
    expect(ErrorBoundary.getDerivedStateFromError(error)).toEqual({ error });
  });
});
