/**
 * Shared browser API client.
 *
 * Pages and feature components use this client (or a hook built on it) — they
 * never construct backend URLs or raw request payloads directly. A 403 maps to
 * a distinct ApiError so the UI can render a controlled forbidden state.
 */

import { env } from "@/env";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiClient {
  get<T>(path: string, query?: Record<string, string>): Promise<T>;
  post<TBody, TResponse>(path: string, body: TBody): Promise<TResponse>;
}

interface ApiAuthenticationState {
  csrfToken: string | null;
  onUnauthorized: (() => void) | null;
}

const authentication: ApiAuthenticationState = {
  csrfToken: null,
  onUnauthorized: null,
};

export function configureApiAuthentication(next: ApiAuthenticationState): void {
  authentication.csrfToken = next.csrfToken;
  authentication.onUnauthorized = next.onUnauthorized;
}

class FetchApiClient implements ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly origin: () => string,
  ) {}

  async get<T>(path: string, query?: Record<string, string>): Promise<T> {
    const url = new URL(this.baseUrl + path, this.origin());
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, value);
      }
    }

    const response = await fetch(url.toString(), { credentials: "include" });
    return this.parse<T>(response);
  }

  async post<TBody, TResponse>(path: string, body: TBody): Promise<TResponse> {
    const url = new URL(this.baseUrl + path, this.origin());
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (authentication.csrfToken !== null) {
      headers["x-csrf-token"] = authentication.csrfToken;
    }
    const response = await fetch(url.toString(), {
      method: "POST",
      credentials: "include",
      headers,
      body: JSON.stringify(body),
    });
    return this.parse<TResponse>(response);
  }

  private async parse<T>(response: Response): Promise<T> {
    if (response.status === 401) {
      authentication.onUnauthorized?.();
      throw new ApiError("请登录", 401);
    }
    if (response.status === 403) {
      throw new ApiError("无权访问", 403);
    }
    if (!response.ok) {
      throw new ApiError(`请求失败 (${response.status})`, response.status);
    }
    return (await response.json()) as T;
  }
}

export function createApiClient(
  baseUrl: string,
  origin: () => string = () => window.location.origin,
): ApiClient {
  return new FetchApiClient(baseUrl, origin);
}

/** Shared client instance bound to the public gateway. */
export const apiClient: ApiClient = createApiClient(env.API_URL);
