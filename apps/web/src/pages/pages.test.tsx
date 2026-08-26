import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { Home } from "./Home";
import { NotFound } from "./NotFound";

describe("terminal page states", () => {
  it("renders the Phase 6 information architecture shell", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    );
    expect(html).toContain("从证据到决策");
    expect(html).toContain("P6-N01");
    expect(html).toContain("研究与模拟");
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
