import { renderToReadableStream } from "react-dom/server";
import { MemoryRouter } from "react-router";
import type * as ReactRouter from "react-router";
import { describe, expect, it, vi } from "vitest";
import { terminalRoutes } from "./route-contract";

let currentRoute = "/";

vi.mock("react-router", async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ReactRouter;
  return {
    ...actual,
    BrowserRouter: ({ children }: { children: React.ReactNode }) => (
      <MemoryRouter initialEntries={[currentRoute]}>{children}</MemoryRouter>
    ),
  };
});

vi.mock("@/components/ui/sonner", () => ({ Toaster: () => null }));

import { App } from "../App";

async function renderRoute(path: string): Promise<string> {
  currentRoute = path;
  const stream = await renderToReadableStream(<App roles={["platform_admin"]} />);
  await stream.allReady;
  return new Response(stream).text();
}

function count(html: string, pattern: RegExp): number {
  return [...html.matchAll(pattern)].length;
}

function assertAriaReferencesResolve(html: string): void {
  const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
  expect(new Set(ids).size, "duplicate element id").toBe(ids.length);

  for (const match of html.matchAll(/\saria-(?:labelledby|describedby)="([^"]+)"/g)) {
    for (const reference of (match[1] ?? "").split(/\s+/).filter(Boolean)) {
      expect(ids, `missing ARIA reference ${reference}`).toContain(reference);
    }
  }
}

function assertInteractiveNames(html: string): void {
  const labels = new Set(
    [...html.matchAll(/<label[^>]*for="([^"]+)"[^>]*>/g)].map((match) => match[1]),
  );
  for (const match of html.matchAll(/<(button|a)([^>]*)>([\s\S]*?)<\/\1>/g)) {
    const attributes = match[2] ?? "";
    const visibleText = (match[3] ?? "").replace(/<[^>]+>/g, "").trim();
    expect(
      /\saria-(?:label|labelledby)="[^"]+"/.test(attributes) || visibleText.length > 0,
      `unnamed ${match[1] ?? "interactive element"}`,
    ).toBe(true);
  }
  for (const match of html.matchAll(/<(input|select|textarea)([^>]*)>/g)) {
    const attributes = match[2] ?? "";
    const id = /\sid="([^"]+)"/.exec(attributes)?.[1];
    expect(
      /\saria-(?:label|labelledby)="[^"]+"/.test(attributes) ||
        (id !== undefined && labels.has(id)),
      `unnamed ${match[1] ?? "form control"}${id === undefined ? "" : ` #${id}`}`,
    ).toBe(true);
  }
}

describe("terminal route accessibility contract", () => {
  it.each(terminalRoutes)("keeps $id structurally navigable", async (route) => {
    const html = await renderRoute(route.href.replace("600519.SH", "000001.SZ"));

    expect(count(html, /<main(?:\s|>)/g), "main landmark count").toBe(1);
    expect(count(html, /<h1(?:\s|>)/g), "page-level heading count").toBe(1);
    expect(html).toContain('href="#terminal-main"');
    expect(html).toContain('aria-label="桌面主导航"');
    expect(html).toContain('aria-label="打开主导航"');
    assertAriaReferencesResolve(html);
    assertInteractiveNames(html);
  });
});
