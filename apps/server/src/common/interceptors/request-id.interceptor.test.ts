import type { CallHandler, ExecutionContext } from "@nestjs/common";
import { firstValueFrom, of } from "rxjs";
import { describe, expect, it } from "vitest";
import { RequestIdInterceptor } from "./request-id.interceptor";

describe("RequestIdInterceptor", () => {
  it("propagates an incoming request ID to the response", async () => {
    const request = {
      headers: { "x-request-id": "test-request-id" },
      method: "GET",
      path: "/api/v1/health",
    };
    const responseHeaders = new Map<string, string>();
    const response = {
      statusCode: 200,
      setHeader: (name: string, value: string) => responseHeaders.set(name, value),
    };
    const http = { getRequest: () => request, getResponse: () => response };
    const context = {
      switchToHttp: () => http,
    } as unknown as ExecutionContext;
    const next = { handle: () => of("ok") } as CallHandler;

    await firstValueFrom(new RequestIdInterceptor().intercept(context, next));

    expect(request).toHaveProperty("requestId", "test-request-id");
    expect(responseHeaders.get("x-request-id")).toBe("test-request-id");
  });
});
