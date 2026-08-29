import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, configureApiAuthentication, createApiClient } from "./api-client";

afterEach(() => {
  configureApiAuthentication({ csrfToken: null, onUnauthorized: null });
  vi.unstubAllGlobals();
});

describe("authenticated API client", () => {
  it("always includes the session cookie and binds unsafe requests to the CSRF token", async () => {
    const fetcher = vi.fn().mockImplementation(
      async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetcher);
    configureApiAuthentication({ csrfToken: "c".repeat(43), onUnauthorized: null });
    const client = createApiClient("/api", () => "http://localhost:5173");

    await client.get("/v1/auth/session");
    await client.post("/v1/auth/logout", {});

    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ credentials: "include" });
    expect(fetcher.mock.calls[1]?.[1]).toMatchObject({
      method: "POST",
      credentials: "include",
      headers: {
        "content-type": "application/json",
        "x-csrf-token": "c".repeat(43),
      },
    });
  });

  it("notifies the auth boundary on a 401 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    const onUnauthorized = vi.fn();
    configureApiAuthentication({ csrfToken: null, onUnauthorized });
    const client = createApiClient("/api", () => "http://localhost:5173");

    await expect(client.get("/v1/protected")).rejects.toEqual(new ApiError("请登录", 401));
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});
