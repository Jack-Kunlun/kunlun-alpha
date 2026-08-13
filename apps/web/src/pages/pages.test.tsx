import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { Home } from "./Home";
import { NotFound } from "./NotFound";

describe("Phase 0 page states", () => {
  it("renders the home loading-independent shell", () => {
    const html = renderToStaticMarkup(<Home />);
    expect(html).toContain("昆仑智策");
    expect(html).toContain("工程基础设施");
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
