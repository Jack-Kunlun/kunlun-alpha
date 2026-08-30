import type { AuthSessionResponse } from "@kunlun/shared-types";
import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { App } from "@/App";
import { Button } from "@/components/ui/button";
import { ApiError, apiClient, configureApiAuthentication } from "@/lib/api-client";
import { LoginPage } from "./login-page";

type AuthStatus = "loading" | "anonymous" | "authenticated" | "error";

interface AuthState {
  status: AuthStatus;
  session: AuthSessionResponse | null;
  message: string | null;
  pending: boolean;
}

export interface AuthContextValue extends AuthState {
  login(username: string, password: string): Promise<void>;
  logout(): Promise<void>;
  refresh(): Promise<void>;
}

const INITIAL_STATE: AuthState = {
  status: "loading",
  session: null,
  message: null,
  pending: false,
};

const AuthContext = createContext<AuthContextValue | null>(null);

function loginMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return "用户名或密码错误";
  if (error instanceof ApiError && error.status === 429) return "登录尝试过多，请稍后重试";
  return "登录服务暂时不可用，请稍后重试";
}

export function AuthProvider({ children }: PropsWithChildren) {
  const [state, setState] = useState<AuthState>(INITIAL_STATE);

  const becomeAnonymous = useCallback(() => {
    configureApiAuthentication({ csrfToken: null, onUnauthorized: null });
    setState({ status: "anonymous", session: null, message: null, pending: false });
  }, []);

  const acceptSession = useCallback(
    (session: AuthSessionResponse) => {
      configureApiAuthentication({
        csrfToken: session.csrfToken,
        onUnauthorized: becomeAnonymous,
      });
      setState({
        status: "authenticated",
        session,
        message: null,
        pending: false,
      });
    },
    [becomeAnonymous],
  );

  const refresh = useCallback(async () => {
    setState((current) => ({ ...current, status: "loading", message: null, pending: false }));
    configureApiAuthentication({ csrfToken: null, onUnauthorized: becomeAnonymous });
    try {
      acceptSession(await apiClient.get<AuthSessionResponse>("/v1/auth/session"));
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 401) {
        becomeAnonymous();
        return;
      }
      setState({
        status: "error",
        session: null,
        message: "无法确认登录状态，请检查本地服务后重试",
        pending: false,
      });
    }
  }, [acceptSession, becomeAnonymous]);

  useEffect(() => {
    let active = true;
    configureApiAuthentication({ csrfToken: null, onUnauthorized: becomeAnonymous });
    void apiClient
      .get<AuthSessionResponse>("/v1/auth/session")
      .then((session) => {
        if (active) acceptSession(session);
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          becomeAnonymous();
          return;
        }
        setState({
          status: "error",
          session: null,
          message: "无法确认登录状态，请检查本地服务后重试",
          pending: false,
        });
      });
    return () => {
      active = false;
      configureApiAuthentication({ csrfToken: null, onUnauthorized: null });
    };
  }, [acceptSession, becomeAnonymous]);

  const login = useCallback(
    async (username: string, password: string) => {
      setState({ status: "anonymous", session: null, message: null, pending: true });
      configureApiAuthentication({ csrfToken: null, onUnauthorized: becomeAnonymous });
      try {
        acceptSession(
          await apiClient.post<{ username: string; password: string }, AuthSessionResponse>(
            "/v1/auth/login",
            { username, password },
          ),
        );
      } catch (error: unknown) {
        setState({
          status: "anonymous",
          session: null,
          message: loginMessage(error),
          pending: false,
        });
      }
    },
    [acceptSession, becomeAnonymous],
  );

  const logout = useCallback(async () => {
    setState((current) => ({ ...current, pending: true }));
    try {
      await apiClient.post<Record<string, never>, { authenticated: false }>("/v1/auth/logout", {});
      becomeAnonymous();
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 401) {
        becomeAnonymous();
        return;
      }
      setState((current) => ({
        ...current,
        message: "退出登录失败，请稍后重试",
        pending: false,
      }));
    }
  }, [becomeAnonymous]);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, logout, refresh }),
    [state, login, logout, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useOptionalAuth(): AuthContextValue | null {
  return useContext(AuthContext);
}

export function AuthenticatedTerminal() {
  const auth = useContext(AuthContext);
  if (auth === null) throw new Error("AuthenticatedTerminal requires AuthProvider");
  if (auth.status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-200">
        <h1 className="sr-only">昆仑智策登录状态</h1>
        <p role="status">正在确认登录状态…</p>
      </main>
    );
  }
  if (auth.status === "error") {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-950 px-4 text-center text-slate-200">
        <h1 className="sr-only">昆仑智策登录状态</h1>
        <p role="alert">{auth.message}</p>
        <Button type="button" onClick={() => void auth.refresh()}>
          重试
        </Button>
      </main>
    );
  }
  if (auth.status !== "authenticated" || auth.session === null) {
    return <LoginPage onLogin={auth.login} pending={auth.pending} error={auth.message} />;
  }
  return <App roles={auth.session.user.roles} />;
}
