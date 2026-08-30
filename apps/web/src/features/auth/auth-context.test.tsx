import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AuthenticatedTerminal, AuthProvider } from "./auth-context";

describe("AuthenticatedTerminal accessibility", () => {
  it("names the initial authentication status page", () => {
    const html = renderToStaticMarkup(
      <AuthProvider>
        <AuthenticatedTerminal />
      </AuthProvider>,
    );

    expect(html).toContain("<h1");
    expect(html).toContain("正在确认登录状态");
    expect(html).toContain('role="status"');
  });
});
