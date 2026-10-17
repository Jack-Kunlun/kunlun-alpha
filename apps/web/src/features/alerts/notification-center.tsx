"use client";

import { useCallback, useEffect, useState } from "react";
import type { InAppNotificationCenter } from "@kunlun/shared-types";
import { Bell, Check, CheckCheck, CircleAlert, RefreshCw } from "lucide-react";
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
import { apiClient } from "@/lib/api-client";

export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const [center, setCenter] = useState<InAppNotificationCenter | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCenter(await apiClient.get<InAppNotificationCenter>("/v1/watchlist-alerts/notifications"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "通知中心加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void apiClient
      .get<InAppNotificationCenter>("/v1/watchlist-alerts/notifications")
      .then((next) => {
        if (active) setCenter(next);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "通知中心加载失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function read(notificationId: string) {
    setPending(true);
    setError(null);
    try {
      setCenter(
        await apiClient.post<Record<string, never>, InAppNotificationCenter>(
          `/v1/watchlist-alerts/notifications/${notificationId}/read`,
          {},
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "通知状态更新失败");
    } finally {
      setPending(false);
    }
  }

  async function readAll() {
    setPending(true);
    setError(null);
    try {
      setCenter(
        await apiClient.post<Record<string, never>, InAppNotificationCenter>(
          "/v1/watchlist-alerts/notifications/read-all",
          {},
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "通知状态更新失败");
    } finally {
      setPending(false);
    }
  }

  const unreadCount = center?.unreadCount ?? 0;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) void refresh();
      }}
    >
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          className="relative"
          aria-label={unreadCount > 0 ? `通知中心，${unreadCount} 条未读` : "通知中心"}
        >
          <Bell aria-hidden="true" className="size-4" />
          {unreadCount > 0 ? (
            <span className="absolute -top-1.5 -right-1.5 min-w-4 rounded-full bg-amber-500 px-1 text-center text-[10px] leading-4 font-semibold text-slate-950">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          ) : null}
        </Button>
      </DialogTrigger>
      <DialogContent className="grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-0 sm:max-w-xl">
        <DialogHeader className="border-b px-6 pt-6 pr-12 pb-4">
          <DialogTitle>通知中心</DialogTitle>
          <DialogDescription>持久保存自选预警及已读状态，仅用于站内研究提醒。</DialogDescription>
        </DialogHeader>
        <NotificationCenterPanel
          center={center}
          loading={loading}
          error={error}
          pending={pending}
          onRefresh={refresh}
          onRead={read}
          onReadAll={readAll}
        />
      </DialogContent>
    </Dialog>
  );
}

export function NotificationCenterPanel({
  center,
  loading,
  error,
  pending,
  onRefresh,
  onRead,
  onReadAll,
}: {
  center: InAppNotificationCenter | null;
  loading: boolean;
  error: string | null;
  pending: boolean;
  onRefresh: () => void | Promise<void>;
  onRead: (notificationId: string) => void | Promise<void>;
  onReadAll: () => void | Promise<void>;
}) {
  return (
    <div className="min-h-0 overflow-y-auto" aria-busy={loading || pending}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-6 py-3">
        <div className="flex items-center gap-2">
          <Badge variant={center?.unreadCount ? "default" : "secondary"}>
            {center?.unreadCount ?? 0} 条未读
          </Badge>
          <span className="text-xs text-muted-foreground">仅站内研究提醒</span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={loading || pending || !center?.unreadCount}
            onClick={() => void onReadAll()}
          >
            <CheckCheck aria-hidden="true" /> 全部已读
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled={loading || pending}
            aria-label="刷新通知"
            onClick={() => void onRefresh()}
          >
            <RefreshCw aria-hidden="true" />
          </Button>
        </div>
      </div>

      {error ? (
        <div role="alert" className="m-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm">
          <div className="flex items-center gap-2 font-medium text-red-700">
            <CircleAlert aria-hidden="true" className="size-4" /> 通知中心暂不可用
          </div>
          <p className="mt-1 text-red-600">{error}</p>
        </div>
      ) : loading && center === null ? (
        <p role="status" className="p-8 text-center text-sm text-muted-foreground">
          正在读取通知…
        </p>
      ) : center?.notifications.length ? (
        <ul className="divide-y">
          {center.notifications.map((item) => {
            const unread = item.readAt === null;
            return (
              <li key={item.notificationId} className={unread ? "bg-amber-50/60" : undefined}>
                <article className="space-y-2 px-6 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate text-sm font-semibold">{item.title}</h3>
                        <Badge variant={statusVariant(item.deliveryStatus)}>
                          {statusLabel(item.deliveryStatus)}
                        </Badge>
                      </div>
                      <p className="mt-1 font-mono text-xs text-muted-foreground">
                        {item.instrumentId}
                      </p>
                    </div>
                    {unread ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={loading || pending}
                        onClick={() => void onRead(item.notificationId)}
                      >
                        <Check aria-hidden="true" /> 标记已读
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">已读</span>
                    )}
                  </div>
                  <p className="text-sm text-foreground/85">{item.body}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatTime(item.availableAt)} · 投递尝试 {item.deliveryAttempts}
                  </p>
                </article>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="p-10 text-center text-sm text-muted-foreground">
          暂无通知。自选规则触发后会显示在这里。
        </p>
      )}
    </div>
  );
}

function statusLabel(status: "PENDING" | "DELIVERED" | "FAILED"): string {
  if (status === "DELIVERED") return "已送达";
  if (status === "FAILED") return "投递失败";
  return "待投递";
}

function statusVariant(
  status: "PENDING" | "DELIVERED" | "FAILED",
): "default" | "destructive" | "outline" {
  if (status === "DELIVERED") return "default";
  if (status === "FAILED") return "destructive";
  return "outline";
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
