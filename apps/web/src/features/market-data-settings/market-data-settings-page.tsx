import { useEffect, useRef, useState, type FormEvent } from "react";
import type {
  MarketDataProvider,
  MarketDataSettingsResponse,
  MarketDataTokenAction,
} from "@kunlun/shared-types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  buildMarketDataSettingsUpdate,
  type MarketDataSettingsDraft,
} from "./market-data-settings-client";
import { useMarketDataSettings, type MarketDataSettingsQuery } from "./use-market-data-settings";

const PROVIDER_LABELS: Record<MarketDataProvider, string> = {
  akshare: "AKShare",
  tushare: "Tushare",
};

function providerLabel(provider: MarketDataProvider): string {
  return PROVIDER_LABELS[provider];
}

export interface MarketDataSettingsDraftSnapshot {
  provider: MarketDataProvider;
  tokenAction: MarketDataTokenAction;
  token: string;
  clearConfirmed: boolean;
}

export function draftFromMarketDataSettings(
  snapshot: MarketDataSettingsResponse,
): MarketDataSettingsDraftSnapshot {
  return {
    provider: snapshot.provider,
    tokenAction: "KEEP",
    token: "",
    clearConfirmed: false,
  };
}

export function shouldSyncMarketDataSettingsDraft({
  draftTouched,
  force,
  lastSyncedRevision,
  nextRevision,
}: {
  draftTouched: boolean;
  force: boolean;
  lastSyncedRevision: number | null;
  nextRevision: number;
}): boolean {
  return force || (!draftTouched && lastSyncedRevision !== nextRevision);
}

function draftErrorMessage(
  action: MarketDataTokenAction,
  provider: MarketDataProvider,
  tokenConfigured = true,
): string {
  if (action === "REPLACE") return "请输入有效 token：1–256 位 ASCII 可打印字符，不能包含空格";
  if (action === "CLEAR" && provider === "tushare") return "Tushare 必须保留有效 token";
  if (action === "CLEAR") return "请确认清除当前 token 后再保存";
  if (action === "KEEP" && provider === "tushare" && !tokenConfigured) {
    return "Tushare 需要配置 token，请选择替换 token";
  }
  return "行情源配置请求无效";
}

function SettingsErrorState({
  query,
  onRetry,
}: {
  query: MarketDataSettingsQuery;
  onRetry: () => void;
}) {
  const message =
    query.status === "forbidden"
      ? "无权访问行情源配置"
      : query.status === "unavailable"
        ? "行情源配置服务暂时不可用，请稍后重试"
        : "加载行情源配置失败，请稍后重试";
  return (
    <section aria-labelledby="market-data-settings-error-title" className="space-y-3">
      <h3 id="market-data-settings-error-title" className="text-base font-semibold">
        配置暂不可用
      </h3>
      <p role="alert" className="text-sm text-destructive">
        {message}
      </p>
      <Button type="button" variant="outline" onClick={onRetry}>
        重试
      </Button>
    </section>
  );
}

export function MarketDataSettingsPage() {
  const { query, saving, saveError, saved, refresh, save, clearSaveError } =
    useMarketDataSettings();
  const data = query.data;
  const [provider, setProvider] = useState<MarketDataProvider>(() => data?.provider ?? "akshare");
  const [tokenAction, setTokenAction] = useState<MarketDataTokenAction>("KEEP");
  const [token, setToken] = useState("");
  const [clearConfirmed, setClearConfirmed] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const draftTouchedRef = useRef(false);
  const initializedRef = useRef(false);
  const lastSyncedRevisionRef = useRef<number | null>(null);
  const forceSyncNextSnapshotRef = useRef(false);
  const draftRevisionRef = useRef<number | null>(null);
  const tokenRef = useRef("");

  useEffect(() => {
    if (data === null || (query.status !== "empty" && query.status !== "success")) return;
    const force = forceSyncNextSnapshotRef.current;
    const shouldSync = shouldSyncMarketDataSettingsDraft({
      draftTouched: draftTouchedRef.current,
      force,
      lastSyncedRevision: lastSyncedRevisionRef.current,
      nextRevision: data.revision,
    });
    lastSyncedRevisionRef.current = data.revision;
    initializedRef.current = true;
    if (!shouldSync) return;

    const nextDraft = draftFromMarketDataSettings(data);
    forceSyncNextSnapshotRef.current = false;
    draftRevisionRef.current = data.revision;
    draftTouchedRef.current = false;
    setProvider(nextDraft.provider);
    setTokenAction(nextDraft.tokenAction);
    tokenRef.current = nextDraft.token;
    setToken(nextDraft.token);
    setClearConfirmed(nextDraft.clearConfirmed);
  }, [data, query.status]);

  useEffect(() => {
    return () => {
      tokenRef.current = "";
    };
  }, []);

  const markDraftTouched = () => {
    draftTouchedRef.current = true;
    setSavedMessage(null);
    setFormError(null);
    clearSaveError();
  };

  const updateToken = (value: string) => {
    tokenRef.current = value;
    setToken(value);
    markDraftTouched();
  };

  const handleProviderChange = (nextProvider: MarketDataProvider) => {
    markDraftTouched();
    setProvider(nextProvider);
    if (nextProvider === "tushare" && tokenAction === "CLEAR") {
      setTokenAction("KEEP");
      setClearConfirmed(false);
    }
  };

  const handleTokenActionChange = (nextAction: MarketDataTokenAction) => {
    if (nextAction === "CLEAR" && provider === "tushare") return;
    markDraftTouched();
    setTokenAction(nextAction);
    if (nextAction !== "REPLACE") {
      tokenRef.current = "";
      setToken("");
    }
    setClearConfirmed(false);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (data === null || saving) return;
    setFormError(null);
    clearSaveError();
    if (tokenAction === "CLEAR" && provider === "tushare") {
      setFormError(draftErrorMessage(tokenAction, provider));
      return;
    }
    if (tokenAction === "KEEP" && provider === "tushare" && !data.tokenConfigured) {
      setFormError(draftErrorMessage(tokenAction, provider, data.tokenConfigured));
      return;
    }
    if (tokenAction === "CLEAR" && !clearConfirmed) {
      setFormError(draftErrorMessage(tokenAction, provider));
      return;
    }

    const draft: MarketDataSettingsDraft = {
      expectedRevision: draftRevisionRef.current ?? data.revision,
      provider,
      tokenAction,
      token,
    };
    let update;
    try {
      update = buildMarketDataSettingsUpdate(draft);
    } catch {
      setFormError(draftErrorMessage(tokenAction, provider));
      return;
    }

    const response = await save(update);
    if (response === null) return;
    draftTouchedRef.current = false;
    draftRevisionRef.current = response.revision;
    lastSyncedRevisionRef.current = response.revision;
    initializedRef.current = true;
    forceSyncNextSnapshotRef.current = false;
    setProvider(response.provider);
    setTokenAction("KEEP");
    tokenRef.current = "";
    setToken("");
    setClearConfirmed(false);
    setFormError(null);
    setSavedMessage(
      `已保存 revision ${response.revision} · 更新时间 ${response.updatedAt ?? "尚未保存"}`,
    );
  };

  const handleCancel = () => {
    if (data === null) return;
    draftTouchedRef.current = false;
    draftRevisionRef.current = data.revision;
    lastSyncedRevisionRef.current = data.revision;
    initializedRef.current = true;
    forceSyncNextSnapshotRef.current = false;
    setProvider(data.provider);
    setTokenAction("KEEP");
    tokenRef.current = "";
    setToken("");
    setClearConfirmed(false);
    setFormError(null);
    setSavedMessage(null);
    clearSaveError();
  };

  const handleRefresh = () => {
    draftTouchedRef.current = false;
    initializedRef.current = false;
    lastSyncedRevisionRef.current = null;
    draftRevisionRef.current = null;
    forceSyncNextSnapshotRef.current = true;
    tokenRef.current = "";
    setToken("");
    setTokenAction("KEEP");
    setClearConfirmed(false);
    setFormError(null);
    setSavedMessage(null);
    clearSaveError();
    refresh();
  };

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-xl font-semibold">行情源配置</h2>
        <p className="text-sm text-muted-foreground">
          管理当前实例的 AKShare / Tushare 采集来源与 token 状态。
        </p>
      </header>

      {query.status === "loading" && (
        <p role="status" className="text-sm text-muted-foreground">
          正在加载行情源配置…
        </p>
      )}

      {(query.status === "error" ||
        query.status === "forbidden" ||
        query.status === "unavailable") && (
        <SettingsErrorState query={query} onRetry={handleRefresh} />
      )}

      {data !== null && (query.status === "empty" || query.status === "success") && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>实例级设置</CardTitle>
              <CardDescription>
                保存后采集进程在下一轮读取；本页不确认运行生效或真实行情连通。
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <p className="text-muted-foreground">当前行情源</p>
                <p className="font-medium">{providerLabel(data.provider)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">token 状态</p>
                <p className="font-medium">{data.tokenConfigured ? "已配置" : "未配置"}</p>
              </div>
              <div>
                <p className="text-muted-foreground">revision / 更新时间</p>
                <p className="font-medium">
                  revision {data.revision} · {data.updatedAt ?? "尚未保存"}
                </p>
              </div>
            </CardContent>
          </Card>

          {query.status === "empty" && (
            <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground">
              当前还是默认配置（revision 0），尚未保存过实例级行情源设置。
            </p>
          )}

          <form
            onSubmit={(event) => void handleSubmit(event)}
            className="space-y-6"
            aria-busy={saving}
          >
            <Card>
              <CardHeader>
                <CardTitle>编辑配置</CardTitle>
                <CardDescription>只提交 provider 与明确选择的 token 操作。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid gap-2">
                  <Label htmlFor="market-data-provider">行情源</Label>
                  <select
                    id="market-data-provider"
                    value={provider}
                    disabled={saving}
                    onChange={(event) =>
                      handleProviderChange(event.target.value as MarketDataProvider)
                    }
                    className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30"
                  >
                    <option value="akshare">AKShare</option>
                    <option value="tushare">Tushare</option>
                  </select>
                </div>

                <fieldset className="space-y-3">
                  <legend className="text-sm font-medium">token 操作</legend>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <label
                      htmlFor="market-data-token-keep"
                      className="flex items-start gap-2 text-sm"
                    >
                      <input
                        id="market-data-token-keep"
                        type="radio"
                        name="market-data-token-action"
                        value="KEEP"
                        checked={tokenAction === "KEEP"}
                        disabled={saving}
                        onChange={() => handleTokenActionChange("KEEP")}
                        className="mt-0.5 accent-primary"
                      />
                      <span>
                        <span className="block font-medium">保持现有 token</span>
                        <span className="text-xs text-muted-foreground">不提交 token</span>
                      </span>
                    </label>
                    <label
                      htmlFor="market-data-token-replace"
                      className="flex items-start gap-2 text-sm"
                    >
                      <input
                        id="market-data-token-replace"
                        type="radio"
                        name="market-data-token-action"
                        value="REPLACE"
                        checked={tokenAction === "REPLACE"}
                        disabled={saving}
                        onChange={() => handleTokenActionChange("REPLACE")}
                        className="mt-0.5 accent-primary"
                      />
                      <span>
                        <span className="block font-medium">替换 token</span>
                        <span className="text-xs text-muted-foreground">仅提交新 token</span>
                      </span>
                    </label>
                    <label
                      htmlFor="market-data-token-clear"
                      className="flex items-start gap-2 text-sm"
                    >
                      <input
                        id="market-data-token-clear"
                        type="radio"
                        name="market-data-token-action"
                        value="CLEAR"
                        checked={tokenAction === "CLEAR"}
                        disabled={saving || provider === "tushare"}
                        onChange={() => handleTokenActionChange("CLEAR")}
                        className="mt-0.5 accent-primary"
                      />
                      <span>
                        <span className="block font-medium">清除 token</span>
                        <span className="text-xs text-muted-foreground">
                          {provider === "tushare" ? "Tushare 必须保留 token" : "需要额外确认"}
                        </span>
                      </span>
                    </label>
                  </div>
                </fieldset>

                <div className="grid gap-2">
                  <Label htmlFor="market-data-token">新 token（仅替换时填写）</Label>
                  <Input
                    id="market-data-token"
                    type="password"
                    autoComplete="new-password"
                    value={token}
                    disabled={saving || tokenAction !== "REPLACE"}
                    onChange={(event) => updateToken(event.target.value)}
                    aria-describedby="market-data-token-help"
                  />
                  <p id="market-data-token-help" className="text-xs text-muted-foreground">
                    token 仅在本次提交中使用，不会回显、存入浏览器或出现在错误提示中。
                  </p>
                </div>

                {tokenAction === "CLEAR" && (
                  <label
                    htmlFor="market-data-token-clear-confirmation"
                    className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm"
                  >
                    <input
                      id="market-data-token-clear-confirmation"
                      type="checkbox"
                      checked={clearConfirmed}
                      disabled={saving}
                      onChange={(event) => {
                        markDraftTouched();
                        setClearConfirmed(event.target.checked);
                      }}
                      className="mt-0.5 accent-primary"
                    />
                    <span>我确认清除当前 token</span>
                  </label>
                )}

                {formError !== null && (
                  <p role="alert" className="text-sm text-destructive">
                    {formError}
                  </p>
                )}
                {saveError !== null && (
                  <div
                    role="alert"
                    className="flex flex-wrap items-center gap-3 text-sm text-destructive"
                  >
                    <span>{saveError}</span>
                    {saveError.includes("其他操作更新") && (
                      <Button type="button" variant="outline" size="sm" onClick={handleRefresh}>
                        刷新配置
                      </Button>
                    )}
                  </div>
                )}
                {(saved || savedMessage !== null) && (
                  <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
                    {savedMessage ?? "配置已保存"}
                  </p>
                )}
              </CardContent>
              <CardFooter className="sticky bottom-0 z-10 justify-end gap-3 border-t bg-background/95 py-4 backdrop-blur">
                <Button type="button" variant="outline" disabled={saving} onClick={handleCancel}>
                  取消
                </Button>
                <Button type="submit" disabled={saving}>
                  {saving ? "保存中…" : "保存配置"}
                </Button>
              </CardFooter>
            </Card>
          </form>
        </>
      )}
    </div>
  );
}
