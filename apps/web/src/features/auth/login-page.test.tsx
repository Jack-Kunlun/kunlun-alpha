import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { LoginPage } from "./login-page";

describe("LoginPage", () => {
  it("renders a password-manager-friendly local administrator form", () => {
    const html = renderToStaticMarkup(<LoginPage onLogin={vi.fn()} pending={false} error={null} />);
    expect(html).toContain("登录昆仑智策");
    expect(html).toContain("<h1");
    expect(html).toContain('autoComplete="username"');
    expect(html).toContain('autoComplete="current-password"');
    expect(html).toContain("历史日线研究环境");
    expect(html).not.toContain("注册");
  });

  it("shows generic login failures without echoing credentials", () => {
    const html = renderToStaticMarkup(
      <LoginPage onLogin={vi.fn()} pending={false} error="用户名或密码错误" />,
    );
    expect(html).toContain("用户名或密码错误");
    expect(html).toContain('role="alert"');
  });

  it("announces a pending login and locks its fields", () => {
    const html = renderToStaticMarkup(<LoginPage onLogin={vi.fn()} pending error={null} />);
    expect(html).toContain('aria-busy="true"');
    expect([...html.matchAll(/<input[^>]*disabled=""/g)]).toHaveLength(2);
    expect(html).toContain("正在验证…");
  });
});
