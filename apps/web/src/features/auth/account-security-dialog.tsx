import type {
  AuthPasswordChangeResponse,
  AuthSessionListResponse,
  AuthSessionRevocationResponse,
  AuthSessionSummary,
} from "@kunlun/shared-types";
import { KeyRound, RefreshCcw, ShieldCheck, UserRoundCog } from "lucide-react";
import { useCallback, useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiClient } from "@/lib/api-client";

const shanghaiTime = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function formatInstant(value: string): string {
  return shanghaiTime.format(new Date(value));
}

function requestMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.status === 403) return "当前密码不正确";
  if (error instanceof ApiError && error.status === 404) return "会话已失效，请刷新列表";
  if (error instanceof ApiError && error.status === 400) return "提交内容不符合密码安全要求";
  return fallback;
}

interface AccountSecurityPanelProps {
  sessions: readonly AuthSessionSummary[];
  sessionsLoading: boolean;
  sessionsError: string | null;
  revokingSessionId: string | null;
  passwordPending: boolean;
  feedback?: string | null;
  feedbackIsError?: boolean;
  onRefresh(): Promise<void>;
  onRevoke(sessionId: string): Promise<void>;
  onChangePassword(currentPassword: string, newPassword: string): Promise<boolean>;
}

export function AccountSecurityPanel({
  sessions,
  sessionsLoading,
  sessionsError,
  revokingSessionId,
  passwordPending,
  feedback = null,
  feedbackIsError = false,
  onRefresh,
  onRevoke,
  onChangePassword,
}: AccountSecurityPanelProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newPassword.length < 12) {
      setFormError("新密码至少需要 12 个字符");
      return;
    }
    if (newPassword !== confirmation) {
      setFormError("两次输入的新密码不一致");
      return;
    }
    if (newPassword === currentPassword) {
      setFormError("新密码不能与当前密码相同");
      return;
    }
    setFormError(null);
    if (await onChangePassword(currentPassword, newPassword)) {
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
    }
  }

  return (
    <div className="grid gap-6">
      <section aria-labelledby="active-sessions-title" className="grid gap-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 id="active-sessions-title" className="font-medium">
              活跃会话
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              仅展示有效的本地管理员会话；凭据和会话摘要不会显示。
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={sessionsLoading}
            aria-busy={sessionsLoading}
            onClick={() => void onRefresh()}
          >
            <RefreshCcw aria-hidden="true" className="size-3.5" />
            刷新
          </Button>
        </div>

        {sessionsLoading && <p role="status">正在读取会话…</p>}
        {sessionsError !== null && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {sessionsError}
          </p>
        )}
        {!sessionsLoading && sessionsError === null && sessions.length === 0 && (
          <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
            暂无有效会话。
          </p>
        )}
        <div className="grid gap-2">
          {sessions.map((session) => (
            <div
              key={session.sessionId}
              className="flex items-center justify-between gap-3 rounded-xl border bg-muted/30 p-3"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <ShieldCheck aria-hidden="true" className="size-4 text-emerald-600" />
                  <span className="font-mono text-xs">会话 …{session.sessionId.slice(-8)}</span>
                  {session.current && <Badge variant="secondary">当前会话</Badge>}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  最近活动 {formatInstant(session.lastSeenAt)} · 最晚到期{" "}
                  {formatInstant(session.absoluteExpiresAt)}
                </p>
              </div>
              {!session.current && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={revokingSessionId !== null}
                  aria-busy={revokingSessionId === session.sessionId}
                  onClick={() => void onRevoke(session.sessionId)}
                >
                  {revokingSessionId === session.sessionId ? "正在撤销…" : "撤销会话"}
                </Button>
              )}
            </div>
          ))}
        </div>
      </section>

      <form
        className="grid gap-4 border-t pt-5"
        aria-busy={passwordPending}
        onSubmit={(event) => void submit(event)}
      >
        <div>
          <h3 className="flex items-center gap-2 font-medium">
            <KeyRound aria-hidden="true" className="size-4" />
            修改密码
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            更新后保留当前会话，并立即撤销其他会话。密码不会写入日志。
          </p>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="account-current-password">当前密码</Label>
          <Input
            id="account-current-password"
            type="password"
            autoComplete="current-password"
            minLength={12}
            maxLength={256}
            required
            value={currentPassword}
            disabled={passwordPending}
            onChange={(event) => setCurrentPassword(event.currentTarget.value)}
          />
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="account-new-password">新密码</Label>
            <Input
              id="account-new-password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={256}
              required
              value={newPassword}
              disabled={passwordPending}
              onChange={(event) => setNewPassword(event.currentTarget.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="account-confirm-password">确认新密码</Label>
            <Input
              id="account-confirm-password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={256}
              required
              value={confirmation}
              disabled={passwordPending}
              onChange={(event) => setConfirmation(event.currentTarget.value)}
            />
          </div>
        </div>
        {(formError !== null || feedback !== null) && (
          <p
            role={formError === null && !feedbackIsError ? "status" : "alert"}
            className={
              formError === null && !feedbackIsError
                ? "text-sm text-emerald-700"
                : "text-sm text-red-700"
            }
          >
            {formError ?? feedback}
          </p>
        )}
        <Button type="submit" disabled={passwordPending} className="justify-self-start">
          {passwordPending ? "正在更新…" : "更新密码"}
        </Button>
      </form>
    </div>
  );
}

export function AccountSecurityDialog({ displayName }: { displayName: string }) {
  const [open, setOpen] = useState(false);
  const [sessions, setSessions] = useState<readonly AuthSessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [revokingSessionId, setRevokingSessionId] = useState<string | null>(null);
  const [passwordPending, setPasswordPending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [feedbackIsError, setFeedbackIsError] = useState(false);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    setSessionsError(null);
    try {
      const result = await apiClient.get<AuthSessionListResponse>("/v1/auth/sessions");
      setSessions(result.sessions);
    } catch (error: unknown) {
      setSessionsError(requestMessage(error, "无法读取活跃会话"));
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  function changeOpen(nextOpen: boolean): void {
    setOpen(nextOpen);
    if (nextOpen) {
      setFeedback(null);
      setFeedbackIsError(false);
      void loadSessions();
    }
  }

  async function revoke(sessionId: string): Promise<void> {
    setRevokingSessionId(sessionId);
    setFeedback(null);
    setFeedbackIsError(false);
    try {
      await apiClient.post<Record<string, never>, AuthSessionRevocationResponse>(
        `/v1/auth/sessions/${sessionId}/revoke`,
        {},
      );
      setFeedback("会话已撤销");
      await loadSessions();
    } catch (error: unknown) {
      setSessionsError(requestMessage(error, "撤销会话失败"));
    } finally {
      setRevokingSessionId(null);
    }
  }

  async function changePassword(currentPassword: string, newPassword: string): Promise<boolean> {
    setPasswordPending(true);
    setFeedback(null);
    setFeedbackIsError(false);
    try {
      const result = await apiClient.post<
        { currentPassword: string; newPassword: string },
        AuthPasswordChangeResponse
      >("/v1/auth/password", { currentPassword, newPassword });
      setFeedback(`密码已更新，已撤销 ${result.revokedOtherSessions} 个其他会话`);
      await loadSessions();
      return true;
    } catch (error: unknown) {
      setFeedback(requestMessage(error, "密码更新失败"));
      setFeedbackIsError(true);
      return false;
    } finally {
      setPasswordPending(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className="max-w-48">
          <UserRoundCog aria-hidden="true" className="size-4" />
          <span className="hidden truncate sm:inline">{displayName}</span>
          <span className="sr-only">打开账户安全设置</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>账户安全</DialogTitle>
          <DialogDescription>
            管理本地管理员密码和浏览器会话；不授予真实账户或下单权限。
          </DialogDescription>
        </DialogHeader>
        <AccountSecurityPanel
          sessions={sessions}
          sessionsLoading={sessionsLoading}
          sessionsError={sessionsError}
          revokingSessionId={revokingSessionId}
          passwordPending={passwordPending}
          feedback={feedback}
          feedbackIsError={feedbackIsError}
          onRefresh={loadSessions}
          onRevoke={revoke}
          onChangePassword={changePassword}
        />
      </DialogContent>
    </Dialog>
  );
}
